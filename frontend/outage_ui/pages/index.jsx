import { useEffect, useState } from 'react';
const api = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
async function call(path, options) { const r = await fetch(api + path, options); if (!r.ok) throw new Error(await r.text()); return r.json(); }
function Status({ children }) { return <span className={`status status-${String(children).toLowerCase().replaceAll('_', '-')}`}>{children}</span>; }

export default function Outages() {
  const [incidents, setIncidents] = useState([]), [tickets, setTickets] = useState([]), [active, setActive] = useState(null);
  const [note, setNote] = useState(''), [modification, setModification] = useState('{}'), [error, setError] = useState('');
  const [form, setForm] = useState({ account_id: 1, symptoms: 'no internet' });
  const load = async () => { try { setIncidents(await call('/api/outages')); setTickets(await call('/api/failure-tickets')); } catch (e) { setError(e.message); } };
  useEffect(() => { load(); }, []);
  const choose = async (x) => { try { setActive(await call('/api/outages/' + x.thread_id)); } catch (e) { setError(e.message); } };
  const create = async (e) => { e.preventDefault(); const x = await call('/api/outages', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ account_id: Number(form.account_id), symptoms: form.symptoms.split(',').map(x => x.trim()).filter(Boolean) }) }); await choose(x); load(); };
  const decision = async (status) => {
    let payload = { actor_id: 'admin', status, notes: note };
    if (status === 'modified') { try { payload.modification = JSON.parse(modification); } catch { setError('Modification must be valid JSON.'); return; } }
    await call('/api/outages/' + active.thread_id + '/hitl', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }); await choose(active); load();
  };
  const field = async (resolved) => { await call('/api/outages/' + active.thread_id + '/field-result', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ resolved }) }); await choose(active); load(); };
  const investigate = async (ticket) => { await call('/api/failure-tickets/' + ticket.ticket_id + '/investigate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ actor_id: 'admin', notes: note }) }); load(); };
  const recover = async (ticket) => { await call('/api/failure-tickets/' + ticket.ticket_id + '/resolve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ actor_id: 'admin', notes: note }) }); load(); };
  return <main><header><p className="eyebrow">OPERATIONS CONSOLE</p><h1>Nextlink Outage Incidents</h1><p className="subtitle">Durable diagnosis, field dispatch, and human approval.</p></header>{error && <p className="error">{error}</p>}
    <section className="panel"><form onSubmit={create}><label>Account<input type="number" value={form.account_id} onChange={e => setForm({ ...form, account_id: e.target.value })} /></label><label>Symptoms<input value={form.symptoms} onChange={e => setForm({ ...form, symptoms: e.target.value })} /></label><button className="primary">Create incident</button></form><button className="secondary" onClick={load}>Refresh</button></section>
    <section className="panel"><h2>Incidents</h2><table><thead><tr><th>Incident</th><th>State</th><th>Updated</th></tr></thead><tbody>{incidents.map(x => <tr key={x.thread_id} onClick={() => choose(x)}><td>{x.incident_id}</td><td><Status>{x.current_node}</Status></td><td>{x.updated_at}</td></tr>)}</tbody></table></section>
    {active && <section className="panel detail"><h2>Incident {active.incident_id}</h2><div className="status-grid"><span><b>State</b><Status>{active.current_state}</Status></span><span><b>Dispatch</b><Status>{active.dispatch_status}</Status></span><span><b>HITL</b><Status>{active.hitl_status}</Status></span><span><b>Ticket</b><Status>{active.ticket_status}</Status></span></div><input value={note} onChange={e => setNote(e.target.value)} placeholder="Admin notes" />
      {active.current_state === 'WAITING_FOR_HUMAN' && <div className="actions"><button className="approve" onClick={() => decision('approved')}>Approve dispatch</button><button className="reject" onClick={() => decision('rejected')}>Reject</button><input value={modification} onChange={e => setModification(e.target.value)} placeholder='Modification JSON, e.g. {"priority":"urgent"}' /><button className="secondary" onClick={() => decision('modified')}>Modify and approve</button></div>}
      {active.current_state === 'WAITING_FOR_FIELD' && <><button onClick={() => field(true)}>Field resolved</button><button onClick={() => field(false)}>Reopen diagnosis</button></>}
      <h3>Hypotheses</h3><pre>{JSON.stringify(active.hypotheses, null, 2)}</pre><h3>MCP tool history</h3><pre>{JSON.stringify(active.tool_history, null, 2)}</pre><h3>Checkpoint history</h3><pre>{JSON.stringify(active.checkpoints, null, 2)}</pre><h3>HITL task</h3><pre>{JSON.stringify(active.hitl_task, null, 2)}</pre></section>}
    <section className="panel"><h2>Failure tickets</h2>{tickets.map(t => <article key={t.ticket_id}><div><b>{t.ticket_id}</b> <Status>{t.status}</Status></div><div className="actions"><button className="secondary" disabled={t.status !== 'open'} onClick={() => investigate(t)}>Start investigation</button><button className="approve" disabled={t.status === 'resolved'} onClick={() => recover(t)}>Resolve and resume</button></div><pre>{t.error_json}</pre></article>)}</section></main>;
}
