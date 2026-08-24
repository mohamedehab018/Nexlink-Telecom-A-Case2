'use client';

import { useEffect, useState } from 'react';

const api = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

async function call(path, options) {
  const r = await fetch(api + path, options);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `Request failed (${r.status})`);
  return body;
}

function GraphBadge({ type }) {
  const colors = {
    outage: 'badge-red',
    order_activation: 'badge-blue',
    sla_dispute: 'badge-amber',
  };
  return <span className={`badge ${colors[type] || 'badge-gray'}`}>{type || 'unknown'}</span>;
}

export default function HitlQueue() {
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actorId, setActorId] = useState('');
  const [notes, setNotes] = useState({});
  const [message, setMessage] = useState(null);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const pending = await call('/api/hitl/tasks?status=pending');
      setTasks(pending);
      setError('');
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const decide = async (taskId, status) => {
    setMessage(null);
    try {
      if (!actorId.trim()) throw new Error('Enter an admin ID first');
      const res = await call(`/api/hitl/tasks/${encodeURIComponent(taskId)}/decide`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor_id: actorId.trim(), status, notes: notes[taskId] || '' }),
      });
      const resume = res.resume_result;
      setMessage(
        `Task '${taskId}' ${status} by ${actorId}` +
        (resume && !resume.error ? ' — graph resumed from its checkpoint.' : '') +
        (resume && resume.error ? ` — resume error: ${resume.error}` : '')
      );
      load();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <>
      <header className="page-header">
        <h1>HITL Queue — Pending Human Approvals</h1>
        <p>Graphs paused waiting for an admin decision. Deciding here resumes the run from its checkpoint.</p>
      </header>

      {error && <div className="alert alert-error">{error}</div>}
      {message && <div className="alert alert-success">{message}</div>}

      <div className="filter-bar">
        <input
          className="form-group"
          style={{ marginBottom: 0, maxWidth: 260 }}
          placeholder="Admin ID (required to decide)"
          value={actorId}
          onChange={(e) => setActorId(e.target.value)}
        />
        <button className="btn btn-secondary btn-sm" onClick={load}>Refresh</button>
      </div>

      {loading ? (
        <div className="card"><div className="spinner" /></div>
      ) : tasks.length === 0 ? (
        <div className="card empty-state"><h3>No pending approvals</h3><p>All graphs are running unattended.</p></div>
      ) : (
        tasks.map((t) => (
          <div className="card" key={t.task_id} style={{ marginBottom: 16 }}>
            <div className="card-header">
              <h2>{String(t.task_id).startsWith('sla-') ? 'SLA dispute review' : t.description || t.task_type}</h2>
              <GraphBadge type={t.graph_type} />
            </div>
            {t.description && (
              <p style={{ fontSize: '.875rem', color: 'var(--muted)', marginBottom: 12 }}>{t.description}</p>
            )}
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: '.8rem', color: 'var(--muted)', marginBottom: 12 }}>
              <span>Task: <code>{t.task_id}</code></span>
              <span>Account: #{t.account_id ?? '—'}</span>
              <span>Type: {t.task_type}</span>
              <span>Run: {String(t.run_id)}</span>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <input
                placeholder="Decision notes (optional)"
                value={notes[t.task_id] || ''}
                onChange={(e) => setNotes((n) => ({ ...n, [t.task_id]: e.target.value }))}
                style={{ flex: 1, minWidth: 200, padding: '8px 12px', border: '1px solid var(--line)', borderRadius: 'var(--radius)', fontSize: '.85rem' }}
              />
              <button className="btn btn-success btn-sm" onClick={() => decide(t.task_id, 'approved')}>Approve</button>
              <button className="btn btn-danger btn-sm" onClick={() => decide(t.task_id, 'rejected')}>Reject</button>
              {String(t.graph_type) !== 'sla_dispute' && (
                <button className="btn btn-secondary btn-sm" onClick={() => decide(t.task_id, 'modified')}>Modify</button>
              )}
            </div>
          </div>
        ))
      )}
    </>
  );
}
