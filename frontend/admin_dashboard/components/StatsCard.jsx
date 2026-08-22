'use client';

export default function StatsCard({ label, value, color = '' }) {
  return (
    <div className="stat-card">
      <div className="label">{label}</div>
      <div className={`value ${color}`}>{value}</div>
    </div>
  );
}
