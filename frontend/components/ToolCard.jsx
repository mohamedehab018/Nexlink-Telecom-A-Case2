'use client';

import ToggleSwitch from './ToggleSwitch';

export default function ToolCard({ tool, onToggle, onDelete }) {
  const capabilityColors = {
    read: 'blue',
    write: 'amber',
    diagnostic: 'green',
    admin: 'red',
    billing: 'amber',
    dispatch: 'blue',
  };

  return (
    <tr>
      <td>
        <div style={{ fontWeight: 600 }}>{tool.name}</div>
        <div style={{ fontSize: '0.8rem', color: 'var(--muted)', marginTop: 2 }}>
          {tool.description}
        </div>
      </td>
      <td>
        <span className={`badge badge-${capabilityColors[tool.capability] || 'gray'}`}>
          {tool.capability}
        </span>
      </td>
      <td>
        <span className="badge badge-gray">{tool.category}</span>
      </td>
      <td style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>
        v{tool.version}
      </td>
      <td>
        <ToggleSwitch
          enabled={tool.enabled}
          onChange={(val) => onToggle(tool.name, val)}
        />
      </td>
      <td>
        <button
          className="btn btn-danger btn-sm"
          onClick={() => onDelete(tool.name)}
        >
          Delete
        </button>
      </td>
    </tr>
  );
}
