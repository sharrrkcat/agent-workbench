import { useEffect, useState } from 'react';
import { ChatInput } from './components/ChatInput';
import { ChatHeader } from './components/ChatHeader';
import { ChatView } from './components/ChatView';
import { ErrorBanner } from './components/ErrorBanner';
import { SessionSidebar } from './components/SessionSidebar';
import { SettingsPage } from './components/SettingsPage';
import { StatusBar } from './components/StatusBar';
import { createWebSocketUrl } from './api/client';
import { useWorkbenchStore } from './store/useWorkbenchStore';

export default function App() {
  const { currentSession, initialize, refreshCurrent, applyRuntimeEvent } = useWorkbenchStore();
  const [path, setPath] = useState(() => window.location.pathname);
  const [wsUnavailable, setWsUnavailable] = useState(false);

  useEffect(() => {
    void initialize();
  }, [initialize]);

  useEffect(() => {
    const onPopState = () => setPath(window.location.pathname);
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  useEffect(() => {
    if (!currentSession || wsUnavailable) return;
    let opened = false;
    const socket = new WebSocket(createWebSocketUrl(currentSession.session_id));
    let closed = false;
    function requestNextEvent() {
      if (!closed && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'next_event' }));
      }
    }
    socket.addEventListener('open', () => {
      opened = true;
      socket.send(JSON.stringify({ type: 'ping' }));
      requestNextEvent();
    });
    socket.addEventListener('message', (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type && payload.type !== 'pong') {
          applyRuntimeEvent(payload);
          if (!['message_started', 'message_delta', 'run_metrics'].includes(payload.type)) {
            void refreshCurrent().catch(() => undefined);
          }
          requestNextEvent();
        }
      } catch {
        // Ignore malformed development messages.
      }
    });
    socket.addEventListener('error', () => {
      if (!opened) {
        setWsUnavailable(true);
      }
    });
    return () => {
      closed = true;
      socket.close();
    };
  }, [currentSession?.session_id, refreshCurrent, applyRuntimeEvent, wsUnavailable]);

  useEffect(() => {
    if (!currentSession || !wsUnavailable) return;
    const timer = window.setInterval(() => {
      void refreshCurrent().catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [currentSession?.session_id, refreshCurrent, wsUnavailable]);

  function navigate(nextPath: string) {
    window.history.pushState({}, '', nextPath);
    setPath(nextPath);
  }

  if (path === '/settings') {
    return <SettingsPage onBack={() => navigate('/')} />;
  }

  return (
    <div className="app-shell">
      <SessionSidebar />
      <main className="workspace">
        <ChatHeader onOpenSettings={() => navigate('/settings')} />
        <ErrorBanner />
        <ChatView />
        <ChatInput />
        <StatusBar />
      </main>
    </div>
  );
}
