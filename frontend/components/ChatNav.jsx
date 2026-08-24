'use client';

import { useState } from 'react';
import { useSessions } from '../app/chat/SessionsProvider';

const AGENTS = [
  { id: 'support', label: 'Support Agent', available: true, description: 'Accounts, troubleshooting & activations' },
  { id: 'billing', label: 'Billing Agent', available: false, description: 'Coming soon' },
  { id: 'dispatch', label: 'Technician Dispatch', available: false, description: 'Coming soon' },
];

function relativeTime(iso) {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return '';
  const mins = Math.round((Date.now() - then.getTime()) / 60000);
  if (mins < 1) return 'now';
  if (mins < 60) return `${mins}m`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)}h`;
  return then.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

export default function ChatNav() {
  const [selected, setSelected] = useState('support');
  const { activeId, sessions, switchTo, startNewChat } = useSessions();

  return (
    <>
      <button type="button" className="new-chat-btn" onClick={startNewChat}>
        <svg viewBox="0 0 24 24" fill="none" strokeWidth={2} stroke="currentColor" aria-hidden>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
        </svg>
        New chat
      </button>

      <div className="sidebar-section">Recent chats</div>
      <nav className="recent-chats" aria-label="Recent chats">
        {sessions.length === 0 && (
          <div className="chat-empty">No conversations yet</div>
        )}
        {sessions.map((s) => (
          <button
            key={s.session_id}
            type="button"
            className={`chat-item${s.session_id === activeId ? ' active' : ''}`}
            onClick={() => switchTo(s.session_id)}
            title={s.title}
          >
            <span className="chat-item-title">{s.title}</span>
            <span className="chat-item-time">{relativeTime(s.created_at)}</span>
          </button>
        ))}
      </nav>

      <div className="sidebar-section">Agent Switcher</div>
      <nav className="agent-switcher" aria-label="Agent switcher">
        {AGENTS.map((agent) => (
          <button
            key={agent.id}
            type="button"
            className={`agent-item${agent.id === selected ? ' active' : ''}`}
            disabled={!agent.available}
            onClick={() => setSelected(agent.id)}
            title={agent.description}
          >
            <span className="agent-dot" aria-hidden />
            {agent.label}
            {!agent.available && <span className="agent-badge">soon</span>}
          </button>
        ))}
      </nav>
    </>
  );
}
