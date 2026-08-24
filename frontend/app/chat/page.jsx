'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useSessions } from './SessionsProvider';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function ChatPage() {
  const { activeId: sessionId, refreshSessions } = useSessions();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const bottomRef = useRef(null);

  // Load durable history from the backend for this session.
  useEffect(() => {
    if (!sessionId) return;
    // Always clear first: a brand-new session 404s below (unknown session),
    // and without this the previous conversation would stay on screen.
    setMessages([]);
    setError('');
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API}/api/chat/history/${sessionId}`);
        if (!res.ok) return; // unknown/new session starts empty
        const data = await res.json();
        if (!cancelled) setMessages(data.messages || []);
      } catch {
        /* backend offline — start with an empty chat */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, sending]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || !sessionId || sending) return;

    setInput('');
    setError('');
    setMessages((prev) => [...prev, { role: 'user', content: text, created_at: new Date().toISOString() }]);
    setSending(true);

    try {
      const res = await fetch(`${API}/api/chat/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `Request failed (${res.status})`);
      }
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: data.reply, created_at: new Date().toISOString() },
      ]);
      refreshSessions(); // a brand-new session should appear in the sidebar
    } catch (err) {
      setError(err.message === 'Failed to fetch'
        ? 'Cannot reach the chat server. Is the backend running on port 8000?'
        : err.message);
    } finally {
      setSending(false);
    }
  }, [input, sessionId, sending, refreshSessions]);

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <>
      <header className="chat-header">
        <div>
          <h1>Nextlink Support</h1>
          <div className="sub">AI assistant for accounts, troubleshooting and activations</div>
        </div>
        <span className="session-pill" title="This is your chat session ID">
          {sessionId ? sessionId.slice(0, 18) + '…' : '…'}
        </span>
      </header>

      {error && (
        <div className="alert-error" role="alert">
          {error}
        </div>
      )}

      <div className="messages">
        {messages.length === 0 && !sending && (
          <div className="empty-state">
            <h3>Hi! How can we help?</h3>
            <p>Ask about error codes, your plan, equipment issues, or account changes.</p>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.content}
            {m.created_at && (
              <span className="msg-time">
                {new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            )}
          </div>
        ))}

        {sending && (
          <div className="typing" aria-label="Agent is typing">
            <span /><span /><span />
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <footer className="composer">
        <input
          type="text"
          placeholder="Type your message…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={sending}
          aria-label="Message"
        />
        <button type="button" className="btn-send" onClick={send} disabled={sending || !input.trim()}>
          Send
        </button>
      </footer>
    </>
  );
}
