import json, sqlite3, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from graphs.order_activation.hitl import HITLManager
from graphs.outage import OutageWorkflow
from shared.checkpointing import CheckpointStore
from shared.hitl import DECISION_STATUSES, HumanDecision, HITLAdapter, SqliteHITLStore, ensure_hitl_schema
from shared.outage_persistence import OutageRepository


class Tools:
    def __init__(self): self.calls = []
    def __call__(self, name, args):
        self.calls.append((name, args))
        if name == 'get_equipment_diagnostics': return {'ok': True, 'status': 'error', 'log': 'HW_FAULT physical line'}
        if name == 'run_network_diagnostic_sweep': return {'ok': True, 'line': 'low optical power'}
        if name == 'lookup_previous_incidents': return {'ok': True, 'recent_tickets': []}
        if name == 'verify_resolution': return {'ok': True, 'verified': True}
        return {'ok': True, 'reference': args['idempotency_key']}


def temp_path():
    f = tempfile.NamedTemporaryFile(suffix='.db', delete=False); f.close()
    return Path(f.name)


class AdapterProtocolTests(unittest.TestCase):
    """1a. SqliteHITLStore satisfies the shared HITLAdapter Protocol."""

    def setUp(self):
        self.store = SqliteHITLStore(str(temp_path()))

    def test_implements_protocol_methods(self):
        # SqliteHITLStore is duck-type compatible with the HITLAdapter Protocol:
        # create_request(run_id, payload) -> str and get_decision(request_id) -> HumanDecision | None
        self.assertIn('create_request', dir(HITLAdapter))
        self.assertIn('get_decision', dir(HITLAdapter))
        rid = self.store.create_request('run-x', {'type': 'dispatch'})
        self.assertIsInstance(rid, str)
        self.assertIsNone(self.store.get_decision(rid))

    def test_pending_returns_none_then_roundtrip(self):
        rid = self.store.create_request('run-1', {'type': 'dispatch'})
        self.assertTrue(rid.startswith('hitl-'))
        self.assertIsNone(self.store.get_decision(rid))
        decision = HumanDecision(status='approved', actor_id='admin', notes='go')
        self.store.commit_decision(rid, decision)
        got = self.store.get_decision(rid)
        self.assertEqual(got, decision)


class ExactOnceTests(unittest.TestCase):
    """1c. Exactly-one decision commit per task."""

    def setUp(self):
        self.store = SqliteHITLStore(str(temp_path()))
        self.rid = self.store.create_request('run-1', {'type': 'dispatch'})

    def test_second_commit_rejected_and_state_unchanged(self):
        first = HumanDecision(status='approved', actor_id='a1', notes='first')
        self.store.commit_decision(self.rid, first)
        with self.assertRaises(ValueError):
            self.store.commit_decision(self.rid, HumanDecision(status='rejected', actor_id='a2', notes='second'))
        row = self.store.task(self.rid)
        self.assertEqual(row['status'], 'approved')
        self.assertEqual(json.loads(row['decision_json'])['actor_id'], 'a1')

    def test_unknown_task_commit_rejected(self):
        with self.assertRaises(ValueError):
            self.store.commit_decision('missing-id', HumanDecision(status='approved', actor_id='a'))

    def test_invalid_decisions_rejected_before_write(self):
        bad = [
            HumanDecision(status='maybe', actor_id='a'),
            HumanDecision(status='modified', actor_id='a'),  # missing payload
            HumanDecision(status='approved', actor_id='a', modified_payload={'x': 1}),  # payload on non-modified
            HumanDecision(status='approved', actor_id=''),  # no actor
        ]
        for d in bad:
            with self.assertRaises(ValueError):
                self.store.commit_decision(self.rid, d)
        self.assertEqual(self.store.task(self.rid)['status'], 'pending')


class ModifiedDecisionTests(unittest.TestCase):
    """1d. Modified decisions flow through the shared contract."""

    def test_modified_roundtrip(self):
        store = SqliteHITLStore(str(temp_path()))
        rid = store.create_request('run-1', {'type': 'dispatch', 'priority': 'normal'})
        mod = HumanDecision(status='modified', actor_id='a', notes='rush it', modified_payload={'priority': 'urgent'})
        store.commit_decision(rid, mod)
        self.assertEqual(store.get_decision(rid), mod)

    def test_statuses_include_modified(self):
        self.assertEqual(DECISION_STATUSES, ('approved', 'rejected', 'modified'))


class UnifiedSchemaTests(unittest.TestCase):
    """1b. One hitl_tasks table serves both graphs without PK collisions."""

    def test_both_graphs_share_one_table(self):
        path = str(temp_path())
        repo = OutageRepository(path)
        mgr = HITLManager(path)
        outage_id = f'hitl-test{uuid4_hex()}'
        repo.create_hitl(outage_id, 'thread-outage-1', {'type': 'dispatch'})
        act_id = mgr.create_approval_request(run_id=7, thread_id=8, account_id=9,
                                             task_type='equipment_cost', description='needs approval')
        store = SqliteHITLStore(path)
        rows = store.tasks()
        self.assertEqual(len(rows), 2)
        types = {r['graph_type'] for r in rows}
        self.assertEqual(types, {'outage', 'order_activation'})
        self.assertIsInstance(act_id, int)
        self.assertEqual(store.task(str(act_id))['task_type'], 'equipment_cost')
        # outage listing stays scoped to outage graph
        self.assertEqual([r['task_id'] for r in repo.hitls()], [outage_id])

    def _make_legacy_outage_db(self, path):
        c = sqlite3.connect(path)
        c.executescript('''
            CREATE TABLE hitl_tasks (
                task_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                status TEXT NOT NULL,
                action_json TEXT NOT NULL,
                decision_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO hitl_tasks VALUES('hitl-old','t1','pending','{"type":"dispatch"}',NULL,'2024-01-01','2024-01-01');
            INSERT INTO hitl_tasks VALUES('hitl-old2','t2','approved','{"type":"dispatch"}','{"status":"approved","actor_id":"a"}','2024-01-01','2024-01-02');
        ''')
        c.commit(); c.close()

    def _make_legacy_activation_db(self, path):
        c = sqlite3.connect(path)
        c.executescript('''
            CREATE TABLE hitl_tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                thread_id INTEGER NOT NULL,
                account_id INTEGER NOT NULL,
                task_type TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
                admin_id TEXT,
                admin_notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                resolved_at DATETIME
            );
            INSERT INTO hitl_tasks(run_id,thread_id,account_id,task_type,description,status,admin_id,admin_notes,resolved_at)
            VALUES(1,2,3,'equipment_cost','desc','approved','admin1','ok','2024-01-02');
            INSERT INTO hitl_tasks(run_id,thread_id,account_id,task_type,description,status)
            VALUES(4,5,6,'config_change','desc2','pending');
        ''')
        c.commit(); c.close()

    def test_migrates_legacy_outage_rows(self):
        path = str(temp_path())
        self._make_legacy_outage_db(path)
        ensure_hitl_schema(path)
        store = SqliteHITLStore(path)
        rows = {r['task_id']: r for r in store.tasks()}
        self.assertEqual(set(rows), {'hitl-old', 'hitl-old2'})
        self.assertEqual(rows['hitl-old']['status'], 'pending')
        self.assertEqual(rows['hitl-old']['graph_type'], 'outage')
        self.assertEqual(store.get_decision('hitl-old2').status, 'approved')

    def test_migrates_legacy_activation_rows(self):
        path = str(temp_path())
        self._make_legacy_activation_db(path)
        ensure_hitl_schema(path)
        store = SqliteHITLStore(path)
        rows = sorted(store.tasks(), key=lambda r: r['task_id'])
        self.assertEqual(len(rows), 2)
        pending = next(r for r in rows if r['status'] == 'pending')
        approved = next(r for r in rows if r['status'] == 'approved')
        self.assertEqual(pending['graph_type'], 'order_activation')
        self.assertEqual(pending['account_id'], 6)
        d = store.get_decision(approved['task_id'])
        self.assertEqual(d.status, 'approved')
        self.assertEqual(d.actor_id, 'admin1')
        self.assertEqual(d.notes, 'ok')

    def test_migration_is_idempotent(self):
        path = str(temp_path())
        self._make_legacy_outage_db(path)
        ensure_hitl_schema(path)
        ensure_hitl_schema(path)
        self.assertEqual(len(SqliteHITLStore(path).tasks()), 2)


class ActivationManagerTests(unittest.TestCase):
    def setUp(self):
        self.mgr = HITLManager(str(temp_path()))

    def _request(self):
        return self.mgr.create_approval_request(
            run_id=1, thread_id=2, account_id=3,
            task_type='equipment_cost', description='Test')

    def test_create_returns_positive_int(self):
        self.assertGreater(self._request(), 0)

    def test_approve_reject_and_double_decide(self):
        tid = self._request()
        ok = self.mgr.approve_task(tid, 'admin1', 'Approved')
        self.assertTrue(ok['success'])
        again = self.mgr.approve_task(tid, 'admin1')
        self.assertFalse(again['success'])
        other = self._request()
        self.assertTrue(self.mgr.reject_task(other, 'admin1', 'Too expensive')['success'])

    def test_missing_task(self):
        self.assertEqual(self.mgr.approve_task(99999, 'a'), {'success': False, 'error': 'Task not found'})

    def test_modify_task_supported(self):
        tid = self._request()
        result = self.mgr.modify_task(tid, 'admin1', {'max_cost': 50}, notes='cap it')
        self.assertTrue(result['success'])
        status = self.mgr.check_approval_status(tid)
        self.assertEqual(status['status'], 'modified')
        history = self.mgr.get_task_history(3)
        self.assertEqual(history[0]['decision']['modification'], {'max_cost': 50})


class OutageWorkflowModifiedTests(unittest.TestCase):
    """End-to-end: modified decision edits pending_action and dispatches once."""

    def test_modify_then_dispatch(self):
        tools = Tools()
        workflow = OutageWorkflow(CheckpointStore(str(temp_path())), tools)
        paused = workflow.advance(workflow.start('i-mod', 3, ['no internet']))
        self.assertEqual(paused['current_state'], 'WAITING_FOR_HUMAN')
        done = workflow.decide_human_action(paused, 'admin', 'modified', notes='urgent',
                                            modification={'priority': 'urgent'})
        self.assertEqual(done['current_state'], 'WAITING_FOR_FIELD')
        self.assertEqual(done['pending_action']['priority'], 'urgent')
        self.assertEqual(sum(n == 'request_dispatch' for n, _ in tools.calls), 1)

    def test_modified_requires_payload(self):
        workflow = OutageWorkflow(CheckpointStore(str(temp_path())), Tools())
        paused = workflow.advance(workflow.start('i-bad', 3, ['no internet']))
        with self.assertRaises(ValueError):
            workflow.decide_human_action(paused, 'admin', 'modified')


def uuid4_hex():
    from uuid import uuid4
    return uuid4().hex


if __name__ == '__main__':
    unittest.main()
