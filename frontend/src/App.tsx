import { useEffect } from 'react';
import { AgentSwitcher } from './components/AgentSwitcher';
import { ChatInput } from './components/ChatInput';
import { ChatView } from './components/ChatView';
import { ErrorBanner } from './components/ErrorBanner';
import { RunPanel } from './components/RunPanel';
import { SessionSidebar } from './components/SessionSidebar';
import { SettingsPanel } from './components/SettingsPanel';
import { StatusBar } from './components/StatusBar';
import { createWebSocketUrl } from './api/client';
import { useWorkbenchStore } from './store/useWorkbenchStore';

export default function App() {
  const { currentSession, initialize, refreshCurrent } = useWorkbenchStore();

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
        <header className="topbar">
          <div>
            <h1>Agent Workbench</h1>
            <p>Local sessions, callable agents, and slash commands.</p>
          </div>
          <AgentSwitcher />
        </header>
        <ErrorBanner />
        <ChatView />
        <ChatInput />
        <StatusBar />
      </main>
      <aside className="right-rail">
        <SettingsPanel />
        <RunPanel />
      </aside>
    </div>
  );
}
