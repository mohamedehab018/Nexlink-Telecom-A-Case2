import '../styles/globals.css';
import '../styles/outage.css';
import AppShell from '../components/AppShell';
import { SessionsProvider } from './chat/SessionsProvider';

export const metadata = {
  title: 'Nexlink',
  description: 'Admin dashboard, support chat, and outage console',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <SessionsProvider>
          <AppShell>{children}</AppShell>
        </SessionsProvider>
      </body>
    </html>
  );
}
