'use client';

import Link from 'next/link';
import ChatNav from './ChatNav';

export default function ChatSidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <h1>
          <span>Nextlink</span> Support
        </h1>
      </div>

      <ChatNav />

      <div className="sidebar-footer">
        <Link href="/" className="back-to-admin">
          ← Back to Admin Console
        </Link>
      </div>
    </aside>
  );
}
