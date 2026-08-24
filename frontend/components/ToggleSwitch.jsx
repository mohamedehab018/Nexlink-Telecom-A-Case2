'use client';

export default function ToggleSwitch({ enabled, onChange, disabled }) {
  return (
    <label className="toggle">
      <input
        type="checkbox"
        checked={enabled}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
      />
      <span className="toggle-slider" />
      <span className={`toggle-state ${enabled ? 'toggle-on' : 'toggle-off'}`}>
        {enabled ? 'Enabled' : 'Disabled'}
      </span>
    </label>
  );
}
