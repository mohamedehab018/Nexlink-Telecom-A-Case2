"""Explicit durable Network Outage Diagnosis and Field Dispatch state graph."""
from __future__ import annotations
from typing import Any, Callable, TypedDict
from uuid import uuid4
from shared.checkpointing import CheckpointStore, save_checkpoint
from shared.outage_persistence import OutageRepository

class OutageState(TypedDict, total=False):
    thread_id: str; incident_id: str; account_id: int; symptoms: list[str]; current_state: str; hypotheses:list[dict]; selected_hypothesis:dict; evidence:list[dict]; tool_history:list[dict]; decision:str; dispatch_status:str; ticket_status:str; hitl_status:str; pending_action:dict; error:dict; completed_effects:dict[str,Any]; checkpoint_id:int; hitl_request_id:str; failure_ticket_id:str
TERMINAL={'COMPLETED','REJECTED'}; WAITING={'WAITING_FOR_HUMAN','WAITING_FOR_FIELD','FAILED'}

class OutageWorkflow:
    """Deterministic routing; bounded LATS and constrained ReAct live inside nodes."""
    allowed_tools={'get_equipment_diagnostics','run_network_diagnostic_sweep','lookup_previous_incidents','request_dispatch','verify_resolution'}
    REACT_MAX_ACTIONS=2
    def __init__(self, store:CheckpointStore, tool:Callable[[str,dict],dict], hitl:Any=None, repository:OutageRepository|None=None): self.store,self.tool,self.hitl,self.repository=store,tool,hitl,repository or OutageRepository(store.path)
    def start(self,incident_id:str,account_id:int,symptoms:list[str],thread_id:str|None=None):
        if not incident_id or account_id<1 or not symptoms or not all(isinstance(x,str) and x.strip() for x in symptoms): raise ValueError('incident_id, positive account_id and symptoms are required')
        return self._checkpoint({'thread_id':thread_id or f'outage-{incident_id}-{uuid4().hex[:8]}','incident_id':incident_id,'account_id':account_id,'symptoms':symptoms,'current_state':'RECEIVED','hypotheses':[],'evidence':[],'tool_history':[],'dispatch_status':'NOT_REQUESTED','ticket_status':'NONE','hitl_status':'NOT_REQUIRED','completed_effects':{}})
    def _checkpoint(self,s): s['checkpoint_id']=save_checkpoint(self.store,s['thread_id'],'outage',s);self.repository.save_run(s);return s
    def _call(self,s,name,args):
        if name not in self.allowed_tools: raise PermissionError(f'{name} is not in constrained outage tool allowlist')
        result=self.tool(name,args)
        if not isinstance(result,dict) or result.get('ok') is False: raise RuntimeError(f'{name} failed: {result}')
        record={'tool':name,'arguments':args,'observation':result};s['tool_history'].append(record);s['evidence'].append({'source':name,'value':result});self.repository.audit(s['thread_id'],name,args,result);return result
    def _lats(self,s):
        blob=str(s['evidence']).lower(); candidates=[('physical_line_fault',.92 if any(x in blob for x in ('fault','optical','signal')) else .32),('area_network_outage',.72 if 'outage' in blob else .38),('customer_equipment_fault',.62 if any(x in blob for x in ('router','modem','equipment')) else .30)]
        s['hypotheses']=[{'hypothesis':n,'confidence':v,'search_depth':1,'supporting_evidence':s['evidence'][-2:],'status':'candidate'} for n,v in candidates];s['selected_hypothesis']=max(s['hypotheses'],key=lambda h:h['confidence']);s['selected_hypothesis']['status']='selected'
    def _constrained_react(self,s):
        """A strictly bounded, state-recorded evidence loop; graph routing stays outside it."""
        for name in ('lookup_previous_incidents','run_network_diagnostic_sweep')[:self.REACT_MAX_ACTIONS]:
            self._call(s,name,{'account_id':s['account_id']})
    def advance(self,s, pause_after: str | None = None):
        """Run until a terminal/waiting state, or pause after a checkpoint for recovery demos.

        ``pause_after`` is deliberately evaluated *after* saving the transition,
        so a killed process always has a durable, valid resume point.
        """
        try:
            while s['current_state'] not in TERMINAL|WAITING:
                n=s['current_state']
                if n=='RECEIVED':s['current_state']='NORMALIZING'
                elif n=='NORMALIZING':s['current_state']='DIAGNOSING'
                elif n=='DIAGNOSING':self._call(s,'get_equipment_diagnostics',{'account_id':s['account_id']});s['current_state']='HYPOTHESIS_GENERATION'
                elif n=='HYPOTHESIS_GENERATION':self._lats(s);s['current_state']='VERIFYING'
                elif n=='VERIFYING':self._constrained_react(s);s['current_state']='DECIDING'
                elif n=='DECIDING':
                    h=s['selected_hypothesis']; human=h['confidence']<.80 or h['hypothesis']=='physical_line_fault'
                    s.update(decision='dispatch_requires_human_approval',hitl_status='REQUIRED',pending_action={'type':'dispatch','hypothesis':h},current_state='HITL') if human else s.update(decision='monitor',current_state='VERIFY_RESOLUTION')
                elif n=='HITL':
                    task=f'hitl-{uuid4().hex}';s['hitl_request_id']=task;self.repository.create_hitl(task,s['thread_id'],s['pending_action']);s.update(hitl_status='WAITING_FOR_HUMAN',current_state='WAITING_FOR_HUMAN')
                elif n=='DISPATCHING':
                    key='dispatch:'+s['thread_id']
                    if key not in s['completed_effects']:s['completed_effects'][key]=self._call(s,'request_dispatch',{'account_id':s['account_id'],'idempotency_key':key})
                    s.update(dispatch_status='SCHEDULED',current_state='WAITING_FOR_FIELD')
                elif n=='VERIFY_RESOLUTION':self._call(s,'verify_resolution',{'account_id':s['account_id']});s['current_state']='COMPLETED'
                self._checkpoint(s)
                if s['current_state'] == pause_after:
                    return s
            return s
        except Exception as exc:
            s.update(error={'node':s.get('current_state'),'account_id':s.get('account_id'),'message':str(exc),'kind':type(exc).__name__},ticket_status='FAILURE_TICKET_OPEN',current_state='FAILED');self._checkpoint(s)
            # Persist the REAL queue ticket id (repository.failure returns
            # the SUPPORT_TICKETS id) linked to this thread via the same id,
            # so resolve-from-queue can find and resume this run.
            tid=f'failure-{uuid4().hex[:8]}'
            self.repository.failure(tid,s['thread_id'],s['error'],s['checkpoint_id'])
            s['failure_ticket_id']=tid
            return self._checkpoint(s)
    def decide_human_action(self,s,actor_id,status,notes='',modification=None):
        if s.get('current_state')!='WAITING_FOR_HUMAN' or status not in {'approved','rejected','modified'}:raise ValueError('invalid HITL decision')
        if status == 'modified' and not modification: raise ValueError('a modified decision requires a modification payload')
        self.repository.decide_hitl(s['hitl_request_id'],{'status':status,'actor_id':actor_id,'notes':notes,'modification':modification})
        if status=='rejected':s.update(hitl_status='REJECTED',dispatch_status='CANCELLED',current_state='REJECTED')
        else:
            if modification:s['pending_action'].update(modification)
            s.update(hitl_status=status.upper(),current_state='DISPATCHING')
        return self.advance(self._checkpoint(s))
    def field_result(self,s,resolved:bool):
        if s.get('current_state')!='WAITING_FOR_FIELD':raise ValueError('run is not waiting for field result')
        s['current_state']='VERIFY_RESOLUTION' if resolved else 'DIAGNOSING';return self.advance(self._checkpoint(s))
    def resume_failure(self,s):
        if s.get('current_state')!='FAILED':return self.advance(s)
        ticket_id=s.get('failure_ticket_id')
        # The queue closes tickets (status 'closed'); accept either wording.
        if not ticket_id or not self.repository.ticket_resolved(ticket_id):
            raise ValueError('a failure ticket must be resolved before the graph can resume')
        s.update(ticket_status='RESOLVED',current_state=(s.get('error') or {}).get('node','DIAGNOSING'),error=None);return self.advance(self._checkpoint(s))
    def approve_human_action(self,s,actor_id,notes=''): return self.decide_human_action(s,actor_id,'approved',notes)
    def reject_human_action(self,s,actor_id,notes=''): return self.decide_human_action(s,actor_id,'rejected',notes)
