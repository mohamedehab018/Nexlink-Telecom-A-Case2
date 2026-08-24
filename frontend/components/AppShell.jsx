'use client';

import { usePathname } from 'next/navigation';
import Link from 'next/link';
import Sidebar from './Sidebar';
import ChatSidebar from './ChatSidebar';

function OutageShell({ children }) {
  return (
    <div className="console-layout">
      <header className="console-topbar">
        <Link href="/outages" className="console-brand">
          <span>🚨</span> Nexlink <strong>Outage Console</strong>
        </Link>
        <nav className="console-nav">
          <Link href="/" className="console-link">
            ← Admin Dashboard
          </Link>
          <a
            href="http://localhost:8000/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="console-link"
          >
            API Docs ↗
          </a>
        </nav>
      </header>
      <main className="console-main">{children}</main>
    </div>
  );
}

export default function AppShell({ children }) {
  const pathname = usePathname();
  const isChat = pathname === '/chat' || pathname.startsWith('/chat/');
  const isOutage = pathname === '/outages' || pathname.startsWith('/outages/');

  if (isChat) {
    return (
      <div className="layout layout-chat">
        <ChatSidebar />
        <main className="chat-main">{children}</main>
      </div>
    );
  }

  if (isOutage) {
    return <OutageShell>{children}</OutageShell>;
  }

  return (
    <div className="layout">
      <Sidebar />
      <main className="main">{children}</main>
    </div>
  );
}
