'use client';
import { createContext, useCallback, useContext, useEffect, useState } from 'react';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const SESSION_KEY = 'nexlink_chat_session';

const SessionsContext = createContext(null);

function newSessionId() {
  return `chat-${crypto.randomUUID().replace(/-/g, '')}`;
}

export function SessionsProvider({ children }) {
  const [activeId, setActiveId] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [activeAgent, setActiveAgent] = useState('support');

  // Restore the last active session on mount (survives refresh), or create one.
  useEffect(() => {
    let sid = null;
    try {
      sid = window.localStorage.getItem(SESSION_KEY);
    } catch {
      /* storage unavailable — session simply won't persist */
    }
    if (!sid) {
      sid = newSessionId();
      try {
        window.localStorage.setItem(SESSION_KEY, sid);
      } catch {}
    }
    setActiveId(sid);
  }, []);

  const switchTo = useCallback((sid) => {
    setActiveId(sid);
    try {
      window.localStorage.setItem(SESSION_KEY, sid);
    } catch {}
  }, []);

  const startNewChat = useCallback(() => switchTo(newSessionId()), [switchTo]);

  const refreshSessions = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/chat/sessions`);
      if (res.ok) setSessions(await res.json());
    } catch {
      /* backend offline — sidebar list stays empty */
    }
  }, []);

  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

  return (
    <SessionsContext.Provider
      value={{ activeId, sessions, switchTo, startNewChat, refreshSessions, activeAgent, setActiveAgent }}
    >
      {children}
    </SessionsContext.Provider>
  );
}

export function useSessions() {
  return useContext(SessionsContext);
}
