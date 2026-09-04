import { useEffect, useState } from 'react';
import { createWebSocketUrl } from './api/client';
import { ChatHeader } from './components/ChatHeader';
import { ChatInput } from './components/ChatInput';
import { ChatView } from './components/ChatView';
import { ErrorBanner } from './components/ErrorBanner';
import { PetOverlay } from './components/PetOverlay';
import { SessionSidebar } from './components/SessionSidebar';
import { SettingsPage } from './components/SettingsPage';
import { StatusBar } from './components/StatusBar';
import { useWorkbenchStore } from './store/useWorkbenchStore';

export default function App() {
  const initialize = useWorkbenchStore((state) => state.initialize);
  const currentSession = useWorkbenchStore((state) => state.currentSession);
  const refreshCurrent = useWorkbenchStore((state) => state.refreshCurrent);
  const applyRuntimeEvent = useWorkbenchStore((state) => state.applyRuntimeEvent);
  const [, rerender] = useState(0);
  useEffect(() => { void initialize(); }, [initialize]);
  useEffect(() => {
    if (!currentSession) return;
    let closed = false;
    const socket = new WebSocket(createWebSocketUrl(currentSession.session_id));
    const next = () => { if (!closed && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'next_event' })); };
    socket.addEventListener('open', () => { socket.send(JSON.stringify({ type: 'ping' })); next(); });
    socket.addEventListener('message', (event) => { try { const value = JSON.parse(event.data) as { type?: string }; if (value.type && value.type !== 'pong') { applyRuntimeEvent(value as never); next(); } } catch { /* ignore malformed events */ } });
    socket.addEventListener('error', () => { if (!closed) void refreshCurrent(); });
    return () => { closed = true; socket.close(); };
  }, [currentSession?.session_id, applyRuntimeEvent, refreshCurrent]);
  useEffect(() => { const onPop = () => rerender((value) => value + 1); window.addEventListener('popstate', onPop); return () => window.removeEventListener('popstate', onPop); }, []);
  if (window.location.pathname === '/settings') return <SettingsPage onBack={() => { window.history.pushState({}, '', '/'); rerender((value) => value + 1); }} />;
  return <div className="app-shell"><SessionSidebar onOpenSettings={() => { window.history.pushState({}, '', '/settings'); rerender((value) => value + 1); }} /><main className="workspace"><ChatHeader onOpenSettings={() => { window.history.pushState({}, '', '/settings'); rerender((value) => value + 1); }} /><ErrorBanner /><ChatView /><PetOverlay /><ChatInput /><StatusBar /></main></div>;
}
