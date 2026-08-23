'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import TopBar from '../components/TopBar';
import StatsCard from '../components/StatsCard';

const api = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [recentTools, setRecentTools] = useState([]);
  const [error, setError] = useState('');

  useEffect(() => {
    async function load() {
      try {
        const [statsRes, toolsRes] = await Promise.all([
          fetch(`${api}/api/tools/stats`),
          fetch(`${api}/api/tools?enabled_only=false`),
        ]);
        if (!statsRes.ok || !toolsRes.ok) throw new Error('Failed to load');
        setStats(await statsRes.json());
        const data = await toolsRes.json();
        setRecentTools(data.tools.slice(0, 5));
      } catch (e) {
        setError(e.message);
      }
    }
    load();
  }, []);

  return (
    <>
      <TopBar
        title="Dashboard"
        subtitle="Overview of your MCP tool ecosystem"
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px', marginBottom: '24px' }}>
        <Link
          href="/chat"
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-lg)',
            padding: '14px 18px',
            textDecoration: 'none',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            boxShadow: 'var(--shadow)',
            transition: 'all 0.15s ease',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--blue)')}
          onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--line)')}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span style={{ fontSize: '1.25rem' }}>💬</span>
            <div>
              <div style={{ fontWeight: '600', fontSize: '0.875rem', color: 'var(--navy)' }}>User Support Chat</div>
              <div style={{ fontSize: '0.72rem', color: 'var(--muted)' }}>/chat • AI Customer Agent</div>
            </div>
          </div>
          <span style={{ color: 'var(--blue)', fontSize: '0.85rem', fontWeight: '600' }}>Open →</span>
        </Link>

        <Link
          href="/outages"
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-lg)',
            padding: '14px 18px',
            textDecoration: 'none',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            boxShadow: 'var(--shadow)',
            transition: 'all 0.15s ease',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--blue)')}
          onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--line)')}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span style={{ fontSize: '1.25rem' }}>🚨</span>
            <div>
              <div style={{ fontWeight: '600', fontSize: '0.875rem', color: 'var(--navy)' }}>Outage Console</div>
              <div style={{ fontSize: '0.72rem', color: 'var(--muted)' }}>/outages • Operations & HITL</div>
            </div>
          </div>
          <span style={{ color: 'var(--blue)', fontSize: '0.85rem', fontWeight: '600' }}>Open →</span>
        </Link>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="stats-grid">
        <StatsCard label="Total Tools" value={stats?.total ?? '—'} color="blue" />
        <StatsCard label="Enabled" value={stats?.enabled ?? '—'} color="green" />
        <StatsCard label="Disabled" value={stats?.disabled ?? '—'} color="amber" />
        <StatsCard
          label="Categories"
          value={stats?.by_category ? Object.keys(stats.by_category).length : '—'}
        />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
        <div className="card">
          <div className="card-header">
            <h2>Recent Tools</h2>
          </div>
          {recentTools.length === 0 ? (
            <div className="empty-state">
              <h3>No tools registered</h3>
              <p>Register your first tool to get started.</p>
            </div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Tool</th>
                  <th>Capability</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {recentTools.map((tool) => (
                  <tr key={tool.name}>
                    <td style={{ fontWeight: 500 }}>{tool.name}</td>
                    <td>
                      <span className="badge badge-blue">{tool.capability}</span>
                    </td>
                    <td>
                      <span className={`badge ${tool.enabled ? 'badge-green' : 'badge-amber'}`}>
                        {tool.enabled ? 'Enabled' : 'Disabled'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <div className="card-header">
            <h2>By Capability</h2>
          </div>
          {stats?.by_capability && Object.keys(stats.by_capability).length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>Capability</th>
                  <th>Count</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(stats.by_capability).map(([cap, count]) => (
                  <tr key={cap}>
                    <td style={{ fontWeight: 500 }}>{cap}</td>
                    <td>{count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="empty-state">
              <h3>No data yet</h3>
              <p>Stats will appear once tools are registered.</p>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
