import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from graphs.outage import OutageWorkflow
from shared.checkpointing import CheckpointStore, load_checkpoint
from shared.hitl import HumanDecision

class Hitl:
    def __init__(self): self.decision=None
    def create_request(self, run_id, payload): return 'human-'+run_id
    def get_decision(self, request_id): return self.decision

class Tools:
    def __init__(self): self.calls=[]
    def __call__(self, name, args):
        self.calls.append((name,args))
        if name == 'get_equipment_diagnostics': return {'ok':True,'status':'error','log':'HW_FAULT physical line'}
        if name == 'run_network_diagnostic_sweep': return {'ok':True,'line':'low optical power'}
        if name == 'lookup_previous_incidents': return {'ok':True,'recent_tickets':[]}
        if name == 'verify_resolution': return {'ok':True,'verified':True}
        return {'ok':True,'reference':args['idempotency_key']}

class OutageWorkflowTests(unittest.TestCase):
    def make(self):
        f=tempfile.NamedTemporaryFile(suffix='.db', delete=False); f.close()
        tools, hitl=Tools(), Hitl()
        return CheckpointStore(f.name), tools, hitl, Path(f.name)
    def test_approval_and_rejection_diverge(self):
        store, tools, hitl, path=self.make(); workflow=OutageWorkflow(store,tools,hitl)
        paused=workflow.advance(workflow.start('i1',3,['no internet']))
        self.assertEqual(paused['current_state'],'WAITING_FOR_HUMAN')
        approved=workflow.approve_human_action(paused,'admin')
        self.assertEqual(approved['current_state'],'WAITING_FOR_FIELD'); self.assertEqual(approved['dispatch_status'],'SCHEDULED')
        self.assertEqual(workflow.field_result(approved, True)['current_state'],'COMPLETED')
        paused=workflow.advance(workflow.start('i2',3,['no internet']))
        rejected=workflow.reject_human_action(paused,'admin')
        self.assertEqual(rejected['dispatch_status'],'CANCELLED')
        self.assertFalse(any(n=='request_dispatch' and a.get('idempotency_key')=='dispatch:i2' for n,a in tools.calls))
    def test_restart_uses_checkpoint_and_does_not_duplicate_dispatch(self):
        store, tools, hitl, path=self.make(); first=OutageWorkflow(store,tools,hitl)
        paused=first.advance(first.start('restart',3,['no internet']))
        # New runtime/store simulates process termination and restart.
        recovered=load_checkpoint(CheckpointStore(path),paused['thread_id'])
        done=OutageWorkflow(CheckpointStore(path),tools,hitl).approve_human_action(recovered,'admin')
        self.assertEqual(done['current_state'],'WAITING_FOR_FIELD')
        self.assertEqual(sum(n=='request_dispatch' for n,_ in tools.calls),1)
