import '../styles/globals.css';
import Sidebar from '../components/Sidebar';

export const metadata = {
  title: 'Nexlink Admin Dashboard',
  description: 'Admin dashboard for managing MCP tools',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <div className="layout">
          <Sidebar />
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
