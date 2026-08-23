'use client';

import { useEffect, useState } from 'react';
import TopBar from '../../components/TopBar';
import ToolCard from '../../components/ToolCard';

const api = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const CAPABILITIES = ['all', 'read', 'write', 'diagnostic', 'admin', 'billing', 'dispatch'];
const CATEGORIES = ['all', 'account', 'equipment', 'ticket', 'knowledge', 'network', 'system'];

export default function ToolsPage() {
  const [tools, setTools] = useState([]);
  const [capability, setCapability] = useState('all');
  const [category, setCategory] = useState('all');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const loadTools = async () => {
    try {
      let url = `${api}/api/tools`;
      if (capability !== 'all') {
        url = `${api}/api/tools/capability/${capability}`;
      } else if (category !== 'all') {
        url = `${api}/api/tools/category/${category}`;
      }
      const res = await fetch(url);
      if (!res.ok) throw new Error('Failed to load tools');
      const data = await res.json();
      setTools(data.tools);
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => { loadTools(); }, [capability, category]);

  const handleToggle = async (name, enabled) => {
    try {
      setError(''); setSuccess('');
      const res = await fetch(`${api}/api/tools/${name}/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) throw new Error('Failed to toggle tool');
      setSuccess(`Tool "${name}" ${enabled ? 'enabled' : 'disabled'}`);
      loadTools();
    } catch (e) { setError(e.message); }
  };

  const handleDelete = async (name) => {
    if (!confirm(`Delete tool "${name}"? This cannot be undone.`)) return;
    try {
      setError(''); setSuccess('');
      const res = await fetch(`${api}/api/tools/${name}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed to delete tool');
      setSuccess(`Tool "${name}" deleted`);
      loadTools();
    } catch (e) { setError(e.message); }
  };

  return (
    <>
      <TopBar title="Tool Management" subtitle="View, toggle, and manage all registered MCP tools" />
      {error && <div className="alert alert-error">{error}</div>}
      {success && <div className="alert alert-success">{success}</div>}
      <div className="card">
        <div className="card-header">
          <h2>All Tools ({tools.length})</h2>
          <div className="filter-bar">
            <select value={capability} onChange={(e) => setCapability(e.target.value)}>
              {CAPABILITIES.map((c) => (<option key={c} value={c}>{c === 'all' ? 'All Capabilities' : c}</option>))}
            </select>
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => (<option key={c} value={c}>{c === 'all' ? 'All Categories' : c}</option>))}
            </select>
          </div>
        </div>
        {tools.length === 0 ? (
          <div className="empty-state"><h3>No tools found</h3><p>Register a new tool or adjust your filters.</p></div>
        ) : (
          <div className="table-wrapper">
            <table>
              <thead><tr><th>Tool</th><th>Capability</th><th>Category</th><th>Version</th><th>Enabled</th><th>Actions</th></tr></thead>
              <tbody>{tools.map((tool) => (<ToolCard key={tool.name} tool={tool} onToggle={handleToggle} onDelete={handleDelete} />))}</tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}
