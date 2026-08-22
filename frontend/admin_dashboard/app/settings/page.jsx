'use client';

import { useEffect, useState } from 'react';
import TopBar from '../../components/TopBar';
import StatsCard from '../../components/StatsCard';

const api = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function SettingsPage() {
  const [stats, setStats] = useState(null);
  const [health, setHealth] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    async function load() {
      try {
        const [statsRes, healthRes] = await Promise.all([
          fetch(`${api}/api/tools/stats`),
          fetch(`${api}/api/health`),
        ]);
        if (statsRes.ok) setStats(await statsRes.json());
        if (healthRes.ok) setHealth(await healthRes.json());
      } catch (e) { setError(e.message); }
    }
    load();
  }, []);

  return (
    <>
      <TopBar title="Settings" subtitle="System information and configuration" />
      {error && <div className="alert alert-error">{error}</div>}
      <div className="stats-grid">
        <StatsCard label="API Status" value={health?.status ?? '—'} color="green" />
        <StatsCard label="Total Tools" value={stats?.total ?? '—'} color="blue" />
        <StatsCard label="Enabled" value={stats?.enabled ?? '—'} color="green" />
        <StatsCard label="Disabled" value={stats?.disabled ?? '—'} color="amber" />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
        <div className="card">
          <div className="card-header"><h2>API Configuration</h2></div>
          <table>
            <tbody>
              <tr><td style={{ fontWeight: 600 }}>API Base URL</td><td style={{ color: 'var(--muted)' }}>{api}</td></tr>
              <tr><td style={{ fontWeight: 600 }}>Tools Endpoint</td><td style={{ color: 'var(--muted)' }}>/api/tools</td></tr>
              <tr><td style={{ fontWeight: 600 }}>Health Endpoint</td><td style={{ color: 'var(--muted)' }}>/api/health</td></tr>
            </tbody>
          </table>
        </div>
        <div className="card">
          <div className="card-header"><h2>Tool Distribution</h2></div>
          {stats?.by_category && Object.keys(stats.by_category).length > 0 ? (
            <table>
              <thead><tr><th>Category</th><th>Count</th></tr></thead>
              <tbody>{Object.entries(stats.by_category).map(([cat, count]) => (<tr key={cat}><td style={{ fontWeight: 500 }}>{cat}</td><td>{count}</td></tr>))}</tbody>
            </table>
          ) : (<div className="empty-state"><h3>No data</h3></div>)}
        </div>
      </div>
    </>
  );
}
