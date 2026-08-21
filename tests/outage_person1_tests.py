"""Run directly: python tests/outage_person1_tests.py (does not require RAG dependencies)."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from graphs.outage import OutageWorkflow
from shared.checkpointing import CheckpointStore, load_checkpoint, resume_run

class Person1OutageTests(unittest.TestCase):
    def setUp(self): self.path=tempfile.NamedTemporaryFile(suffix='.db',delete=False).name; self.calls=[]
    def graph(self,fail=False):
        def tool(name,args):
            self.calls.append(name)
            return {'ok':not fail,'status':'physical fault' if name=='get_equipment_diagnostics' else 'ok'}
        return OutageWorkflow(CheckpointStore(self.path),tool)
    def test_hitl_checkpoint_and_resume(self):
        g=self.graph(); s=g.advance(g.start('i',1,['offline'],'thread'))
        self.assertEqual(s['current_state'],'WAITING_FOR_HUMAN'); self.assertEqual(load_checkpoint(CheckpointStore(self.path),'thread')['current_state'],'WAITING_FOR_HUMAN')
        s=g.decide_human_action(s,'admin','approved'); self.assertEqual(s['current_state'],'WAITING_FOR_FIELD')
        self.assertEqual(g.field_result(s,True)['current_state'],'COMPLETED')
    def test_failure_ticket_and_react_allowlist(self):
        g=self.graph(True); s=g.advance(g.start('f',1,['offline'],'failed'))
        self.assertEqual(s['current_state'],'FAILED'); self.assertEqual(g.repository.ticket(s['failure_ticket_id'])['status'],'open')
        with self.assertRaises(PermissionError):g._call(s,'arbitrary_tool',{})
    def test_resume_run(self):
        g=self.graph(); g.start('r',1,['offline'],'restart'); self.assertEqual(resume_run(CheckpointStore(self.path),'restart',lambda s:s)['thread_id'],'restart')
if __name__=='__main__':unittest.main(verbosity=2)
