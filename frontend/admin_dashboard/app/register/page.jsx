'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import TopBar from '../../components/TopBar';

const api = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const CAPABILITIES = ['read', 'write', 'diagnostic', 'admin', 'billing', 'dispatch'];
const CATEGORIES = ['account', 'equipment', 'ticket', 'knowledge', 'network', 'system'];

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    name: '', description: '', capability: 'read', category: 'account', version: '1.0.0', author: 'admin',
  });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${api}/api/tools`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || 'Failed to register tool');
      }
      router.push('/tools');
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <TopBar title="Register Tool" subtitle="Add a new MCP tool to the runtime" />
      <div className="card" style={{ maxWidth: 640 }}>
        {error && <div className="alert alert-error">{error}</div>}
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Tool Name</label>
            <input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. get_account_summary" required />
          </div>
          <div className="form-group">
            <label>Description</label>
            <textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="What does this tool do?" rows={3} required />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <div className="form-group">
              <label>Capability</label>
              <select value={form.capability} onChange={(e) => setForm({ ...form, capability: e.target.value })}>
                {CAPABILITIES.map((c) => (<option key={c} value={c}>{c}</option>))}
              </select>
            </div>
            <div className="form-group">
              <label>Category</label>
              <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                {CATEGORIES.map((c) => (<option key={c} value={c}>{c}</option>))}
              </select>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <div className="form-group">
              <label>Version</label>
              <input type="text" value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} placeholder="1.0.0" />
            </div>
            <div className="form-group">
              <label>Author</label>
              <input type="text" value={form.author} onChange={(e) => setForm({ ...form, author: e.target.value })} placeholder="admin" />
            </div>
          </div>
          <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
            <button type="submit" className="btn btn-primary" disabled={loading}>{loading ? 'Registering...' : 'Register Tool'}</button>
            <button type="button" className="btn btn-secondary" onClick={() => router.push('/tools')}>Cancel</button>
          </div>
        </form>
      </div>
    </>
  );
}
