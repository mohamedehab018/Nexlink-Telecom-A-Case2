'use client';

import { useEffect, useState } from 'react';
import TopBar from '../../components/TopBar';
import StatsCard from '../../components/StatsCard';

const api = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const CATEGORIES = ['all', 'troubleshooting', 'policy', 'hardware', 'knowledge'];

export default function RAGPage() {
  const [documents, setDocuments] = useState([]);
  const [stats, setStats] = useState(null);
  const [category, setCategory] = useState('all');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [form, setForm] = useState({
    doc_id: '', text: '', category: 'knowledge', model: 'all', doc_date: '2026-01-01', source_doc: '',
  });
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const load = async () => {
    try {
      setLoading(true);
      const [docsRes, statsRes] = await Promise.all([
        fetch(`${api}/api/rag/documents`),
        fetch(`${api}/api/rag/stats`),
      ]);
      if (docsRes.ok) {
        const data = await docsRes.json();
        setDocuments(data.documents);
      }
      if (statsRes.ok) setStats(await statsRes.json());
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const filtered = category === 'all' ? documents : documents.filter(d => d.category === category);

  const handleDelete = async (docId) => {
    if (!confirm(`Delete document "${docId}"? This removes all its chunks from the vector store.`)) return;
    try {
      setError(''); setSuccess('');
      const res = await fetch(`${api}/api/rag/documents/${docId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed to delete document');
      setSuccess(`Document "${docId}" deleted`);
      setSelectedDoc(null);
      load();
    } catch (e) { setError(e.message); }
  };

  const handleAdd = async (e) => {
    e.preventDefault();
    setError(''); setSuccess(''); setSubmitting(true);
    try {
      const res = await fetch(`${api}/api/rag/documents`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || 'Failed to add document');
      }
      setSuccess(`Document "${form.doc_id}" added`);
      setShowAddForm(false);
      setForm({ doc_id: '', text: '', category: 'knowledge', model: 'all', doc_date: '2026-01-01', source_doc: '' });
      load();
    } catch (e) { setError(e.message); }
    finally { setSubmitting(false); }
  };

  return (
    <>
      <TopBar title="RAG Documents" subtitle="Manage documents in the knowledge base" />

      {error && <div className="alert alert-error">{error}</div>}
      {success && <div className="alert alert-success">{success}</div>}

      {loading ? (
        <div className="card" style={{ textAlign: 'center', padding: '64px 24px' }}>
          <div className="spinner" />
          <p style={{ marginTop: '16px', color: 'var(--muted)' }}>Loading documents...</p>
        </div>
      ) : (
      <>
      <div className="stats-grid">
        <StatsCard label="Documents" value={stats?.total_documents ?? '—'} color="blue" />
        <StatsCard label="Total Chunks" value={stats?.total_chunks ?? '—'} color="green" />
        <StatsCard label="Categories" value={stats?.by_category ? Object.keys(stats.by_category).length : '—'} />
        <StatsCard label="Models" value={stats?.by_model ? Object.keys(stats.by_model).length : '—'} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
        <div className="card">
          <div className="card-header">
            <h2>Documents ({filtered.length})</h2>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              <select value={category} onChange={(e) => setCategory(e.target.value)} style={{ padding: '6px 10px', border: '1px solid var(--line)', borderRadius: 'var(--radius)', fontSize: '0.8rem' }}>
                {CATEGORIES.map(c => <option key={c} value={c}>{c === 'all' ? 'All Categories' : c}</option>)}
              </select>
              <button className="btn btn-primary btn-sm" onClick={() => setShowAddForm(!showAddForm)}>
                {showAddForm ? 'Cancel' : '+ Add Document'}
              </button>
            </div>
          </div>

          {showAddForm && (
            <form onSubmit={handleAdd} style={{ marginBottom: '20px', padding: '16px', background: '#f8fafc', borderRadius: 'var(--radius)' }}>
              <div className="form-group">
                <label>Document ID</label>
                <input type="text" value={form.doc_id} onChange={e => setForm({...form, doc_id: e.target.value})} placeholder="e.g. my-new-guide" required />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div className="form-group">
                  <label>Category</label>
                  <select value={form.category} onChange={e => setForm({...form, category: e.target.value})}>
                    <option value="knowledge">knowledge</option>
                    <option value="troubleshooting">troubleshooting</option>
                    <option value="policy">policy</option>
                    <option value="hardware">hardware</option>
                  </select>
                </div>
                <div className="form-group">
                  <label>Model</label>
                  <select value={form.model} onChange={e => setForm({...form, model: e.target.value})}>
                    <option value="all">all</option>
                    <option value="Nextlink-Coax-V2">Nextlink-Coax-V2</option>
                    <option value="Nextlink-Optic-V1">Nextlink-Optic-V1</option>
                    <option value="Nextlink-WiFi-V3">Nextlink-WiFi-V3</option>
                  </select>
                </div>
              </div>
              <div className="form-group">
                <label>Document Content (Markdown)</label>
                <textarea value={form.text} onChange={e => setForm({...form, text: e.target.value})} rows={8} placeholder="Paste your markdown document here..." required style={{ fontFamily: 'monospace', fontSize: '0.8rem' }} />
              </div>
              <button type="submit" className="btn btn-primary btn-sm" disabled={loading}>
                {loading ? 'Adding...' : 'Add Document'}
              </button>
            </form>
          )}

          <div className="table-wrapper">
            <table>
              <thead><tr><th>Document</th><th>Category</th><th>Model</th><th>Chunks</th><th></th></tr></thead>
              <tbody>
                {filtered.map(doc => (
                  <tr key={doc.doc_id} onClick={() => setSelectedDoc(doc)} style={{ cursor: 'pointer' }}>
                    <td>
                      <div style={{ fontWeight: 500 }}>{doc.doc_id}</div>
                      <div style={{ fontSize: '0.75rem', color: 'var(--muted)' }}>{doc.source_doc}</div>
                    </td>
                    <td><span className={`badge badge-${doc.category === 'policy' ? 'amber' : doc.category === 'hardware' ? 'blue' : doc.category === 'troubleshooting' ? 'red' : 'gray'}`}>{doc.category}</span></td>
                    <td style={{ fontSize: '0.8rem' }}>{doc.model}</td>
                    <td>{doc.chunk_count}</td>
                    <td>
                      <button className="btn btn-danger btn-sm" onClick={(e) => { e.stopPropagation(); handleDelete(doc.doc_id); }}>Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <h2>{selectedDoc ? selectedDoc.doc_id : 'Document Details'}</h2>
          </div>
          {selectedDoc ? (
            <div>
              <table>
                <tbody>
                  <tr><td style={{ fontWeight: 600 }}>Source</td><td>{selectedDoc.source_doc}</td></tr>
                  <tr><td style={{ fontWeight: 600 }}>Category</td><td><span className="badge badge-blue">{selectedDoc.category}</span></td></tr>
                  <tr><td style={{ fontWeight: 600 }}>Model</td><td>{selectedDoc.model}</td></tr>
                  <tr><td style={{ fontWeight: 600 }}>Date</td><td>{selectedDoc.doc_date}</td></tr>
                  <tr><td style={{ fontWeight: 600 }}>Chunks</td><td>{selectedDoc.chunk_count}</td></tr>
                </tbody>
              </table>
              <div style={{ marginTop: '16px' }}>
                <button className="btn btn-danger btn-sm" onClick={() => handleDelete(selectedDoc.doc_id)}>Delete Document</button>
              </div>
            </div>
          ) : (
            <div className="empty-state">
              <h3>Select a document</h3>
              <p>Click a document in the list to view its details.</p>
            </div>
          )}
        </div>
      </div>
      </>
      )}
    </>
  );
}
