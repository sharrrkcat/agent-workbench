import { useEffect, useState } from 'react';
import { ChatInput } from './components/ChatInput';
import { ChatHeader } from './components/ChatHeader';
import { ChatView } from './components/ChatView';
import { ErrorBanner } from './components/ErrorBanner';
import { SessionSidebar } from './components/SessionSidebar';
import { SettingsDrawer } from './components/SettingsDrawer';
import { StatusBar } from './components/StatusBar';
import { createWebSocketUrl } from './api/client';
import { useWorkbenchStore } from './store/useWorkbenchStore';

export default function App() {
  const { currentSession, initialize, refreshCurrent } = useWorkbenchStore();
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    void initialize();
  }, [initialize]);

  useEffect(() => {
    if (!currentSession) return;
    const socket = new WebSocket(createWebSocketUrl(currentSession.session_id));
    socket.addEventListener('open', () => socket.send(JSON.stringify({ type: 'ping' })));
    socket.addEventListener('message', (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type && payload.type !== 'pong') {
          void refreshCurrent();
        }
      } catch {
        // Ignore malformed development messages.
      }
    });
    return () => socket.close();
  }, [currentSession?.session_id, refreshCurrent]);

  return (
    <div className="app-shell">
      <SessionSidebar />
      <main className="workspace">
        <ChatHeader onOpenSettings={() => setSettingsOpen(true)} />
        <ErrorBanner />
        <ChatView />
        <ChatInput />
        <StatusBar />
      </main>
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
