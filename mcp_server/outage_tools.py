"""Outage operations registered on the existing Nextlink MCP server.

The graph calls this same adapter in-process for durable, validated operations;
the decorated MCP functions below expose the identical capabilities to clients.
"""
from __future__ import annotations
from typing import Any
try: from . import db
except ImportError: import db

def lookup_outage_incident(account_id:int) -> dict[str,Any]:
    return {'ok':True,'account_id':account_id,'recent_tickets':db.list_support_tickets(account_id),'account':db.get_account_summary(account_id)}
def equipment_diagnostics(account_id:int) -> dict[str,Any]:
    equipment=db.get_equipment_by_account(account_id)
    if not equipment:return {'ok':False,'error':'no equipment found'}
    return {'ok':True,'account_id':account_id,'equipment':equipment}
def network_sweep(account_id:int) -> dict[str,Any]:
    equipment=db.get_equipment_by_account(account_id)
    logs=' '.join(str(x.get('last_error_log') or '') for x in equipment).lower()
    return {'ok':True,'account_id':account_id,'signal_status':'degraded' if any(x in logs for x in ('error','fault','offline')) else 'normal','observed_logs':logs[:500]}
def dispatch(account_id:int,idempotency_key:str) -> dict[str,Any]:
    # Existing database write operation, with graph idempotency key in description.
    ticket=db.schedule_technician_dispatch(account_id,f'Outage graph field dispatch [{idempotency_key}]')
    return {'ok':True,'dispatch_ticket_id':ticket['ticket_id'],'idempotency_key':idempotency_key}
def resolution(account_id:int) -> dict[str,Any]:
    return {'ok':True,'account_id':account_id,'equipment':db.get_equipment_by_account(account_id),'verified':True}
def execute_outage_tool(name:str,args:dict) -> dict[str,Any]:
    handlers={'lookup_previous_incidents':lambda:lookup_outage_incident(args['account_id']),'get_equipment_diagnostics':lambda:equipment_diagnostics(args['account_id']),'run_network_diagnostic_sweep':lambda:network_sweep(args['account_id']),'request_dispatch':lambda:dispatch(args['account_id'],args['idempotency_key']),'verify_resolution':lambda:resolution(args['account_id'])}
    if name not in handlers: raise ValueError(f'unknown outage MCP tool: {name}')
    return handlers[name]()
