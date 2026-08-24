'use client';

import { useEffect, useState } from 'react';

const api = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

async function call(path, options) {
  const r = await fetch(api + path, options);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `Request failed (${r.status})`);
  return body;
}

function Status({ status }) {
  const cls = { open: 'badge-red', ongoing: 'badge-amber', closed: 'badge-green' };
  return <span className={`badge ${cls[String(status).toLowerCase()] || 'badge-gray'}`}>{status}</span>;
}

export default function TicketsQueue() {
  const [tickets, setTickets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actorId, setActorId] = useState('');
  const [notes, setNotes] = useState({});
  const [message, setMessage] = useState(null);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      setTickets(await call('/api/failure-tickets'));
      setError('');
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const act = async (ticketId, action) => {
    setMessage(null);
    try {
      if (!actorId.trim()) throw new Error('Enter an admin ID first');
      await call(`/api/failure-tickets/${encodeURIComponent(ticketId)}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          actor_id: actorId.trim(),
          notes: notes[ticketId] || (action === 'resolve' ? 'Resolved via Tickets Queue' : 'Under investigation'),
          resolved: action === 'resolve',
        }),
      });
      setMessage(`Ticket '${ticketId}' ${action === 'resolve' ? 'resolved' : 'moved to investigating'} by ${actorId}`);
      load();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <>
      <header className="page-header">
        <h1>Tickets Queue — Open &amp; Investigating</h1>
        <p>Unplanned mid-node failures surfaced as tickets. Resolving one lets the failed run resume from its checkpoint.</p>
      </header>

      {error && <div className="alert alert-error">{error}</div>}
      {message && <div className="alert alert-success">{message}</div>}

      <div className="filter-bar">
        <input
          className="form-group"
          style={{ marginBottom: 0, maxWidth: 260 }}
          placeholder="Admin ID (required to act)"
          value={actorId}
          onChange={(e) => setActorId(e.target.value)}
        />
        <button className="btn btn-secondary btn-sm" onClick={load}>Refresh</button>
      </div>

      {loading ? (
        <div className="card"><div className="spinner" /></div>
      ) : tickets.length === 0 ? (
        <div className="card empty-state"><h3>No unresolved tickets</h3><p>No graph runs are currently failed or under investigation.</p></div>
      ) : (
        <div className="table-wrapper card" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>Ticket</th><th>Account</th><th>Type</th><th>Status</th><th>Description</th><th>Notes</th><th>Created</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {tickets.map((t) => (
                <tr key={t.ticket_id}>
                  <td><code>#{t.ticket_id}</code></td>
                  <td>{t.account_id}</td>
                  <td>{t.ticket_type}</td>
                  <td><Status status={t.status} /></td>
                  <td style={{ maxWidth: 320, whiteSpace: 'pre-wrap' }}>{t.description}</td>
                  <td>
                    <input
                      placeholder="Notes"
                      value={notes[t.ticket_id] || ''}
                      onChange={(e) => setNotes((n) => ({ ...n, [t.ticket_id]: e.target.value }))}
                      style={{ width: '100%', minWidth: 120, padding: '6px 10px', border: '1px solid var(--line)', borderRadius: 'var(--radius)', fontSize: '.8rem' }}
                    />
                  </td>
                  <td style={{ fontSize: '.78rem', color: 'var(--muted)' }}>
                    {t.created_at ? new Date(t.created_at).toLocaleString() : '—'}
                  </td>
                  <td>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      {String(t.status).toLowerCase() === 'open' && (
                        <button className="btn btn-secondary btn-sm" onClick={() => act(t.ticket_id, 'investigate')}>Investigate</button>
                      )}
                      <button className="btn btn-success btn-sm" onClick={() => act(t.ticket_id, 'resolve')}>Resolve</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p style={{ marginTop: 12, fontSize: '.78rem', color: 'var(--muted)' }}>
        Tip: type notes per ticket before acting — they are stored in the ticket description.
      </p>
    </>
  );
}
