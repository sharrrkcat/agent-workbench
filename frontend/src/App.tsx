import { useCallback, useEffect, useRef, useState } from 'react';
import { createWebSocketUrl } from './api/url';
import { ChatHeader } from './components/ChatHeader';
import { ChatInput } from './components/ChatInput';
import { ChatView } from './components/ChatView';
import { ErrorBanner } from './components/ErrorBanner';
import { SessionSidebar } from './components/SessionSidebar';
import { SettingsPage } from './components/SettingsPage';
import { StatusBar } from './components/StatusBar';
import { SidebarInset, SidebarProvider } from './components/ui/sidebar';
import { useWorkbenchStore } from './store/useWorkbenchStore';
import { useModelEvents } from './hooks/useModelEvents';
import type { LeaveGuard } from './components/settings/resources/ResourceUI';

type Location = { pathname: string; search: string; url: string; index: number };
const readLocation = (): Location => ({
  pathname: window.location.pathname,
  search: window.location.search,
  url: window.location.pathname + window.location.search + window.location.hash,
  index: window.history.state?.workbenchIndex ?? 0,
});

export default function App() {
  useModelEvents();
  const initialize = useWorkbenchStore((state) => state.initialize);
  const currentSession = useWorkbenchStore((state) => state.currentSession);
  const refreshCurrent = useWorkbenchStore((state) => state.refreshCurrent);
  const applyRuntimeEvent = useWorkbenchStore((state) => state.applyRuntimeEvent);
  const [location, setLocation] = useState(readLocation);
  const committed = useRef(location);
  const navigating = useRef(false);
  const leaveSettings = useRef<LeaveGuard>(async () => true);
  const setLeaveSettings = useCallback((guard: LeaveGuard) => {
    leaveSettings.current = guard;
  }, []);
  const commit = useCallback((next: Location) => {
    committed.current = next;
    setLocation(next);
  }, []);
  const navigate = useCallback(
    async (url: string, replace = false) => {
      if (navigating.current || url === committed.current.url) return;
      navigating.current = true;
      try {
        if (committed.current.pathname === '/settings' && !(await leaveSettings.current())) return;
        const index = committed.current.index + (replace ? 0 : 1);
        window.history[replace ? 'replaceState' : 'pushState']({ workbenchIndex: index }, '', url);
        commit(readLocation());
      } finally {
        navigating.current = false;
      }
    },
    [commit],
  );
  useEffect(() => {
    void initialize();
  }, [initialize]);
  useEffect(() => {
    if (!currentSession) return;
    let closed = false;
    let socket: WebSocket;
    let reconnect: ReturnType<typeof setTimeout> | undefined;
    function connect() {
      socket = new WebSocket(createWebSocketUrl(currentSession!.session_id));
      const next = () => {
        if (!closed && socket.readyState === WebSocket.OPEN)
          socket.send(JSON.stringify({ type: 'next_event' }));
      };
      socket.addEventListener('open', () => {
        void refreshCurrent();
        next();
      });
      socket.addEventListener('message', (event) => {
        if (closed) return;
        try {
          const value = JSON.parse(event.data) as { type?: string };
          if (value.type && value.type !== 'pong') {
            applyRuntimeEvent(value as never);
            next();
          }
        } catch {
          /* ignore malformed events */
        }
      });
      socket.addEventListener('close', () => {
        if (!closed) reconnect = setTimeout(connect, 1500);
      });
    }
    connect();
    return () => {
      closed = true;
      clearTimeout(reconnect);
      socket.close();
    };
  }, [currentSession?.session_id, applyRuntimeEvent, refreshCurrent]);
  useEffect(() => {
    window.history.replaceState({ workbenchIndex: committed.current.index }, '', committed.current.url);
    let transition: {
      target: Location;
      phase: 'restoring' | 'confirming' | 'replaying';
      allowed?: boolean;
    } | null = null;
    let live = true;
    const settle = () => {
      if (
        !transition ||
        transition.phase !== 'confirming' ||
        transition.allowed === undefined ||
        readLocation().index !== committed.current.index
      )
        return;
      if (transition.allowed) {
        transition.phase = 'replaying';
        window.history.go(transition.target.index - committed.current.index);
      } else {
        transition = null;
        navigating.current = false;
      }
    };
    const onPop = () => {
      const target = readLocation();
      if (transition) {
        if (transition.phase === 'replaying') {
          commit(target);
          transition = null;
          navigating.current = false;
          return;
        }
        if (target.index !== committed.current.index) {
          window.history.go(committed.current.index - target.index);
          return;
        }
        if (transition.phase === 'restoring') {
          transition.phase = 'confirming';
          const current = transition;
          void leaveSettings.current().then((allowed) => {
            if (!live || transition !== current) return;
            current.allowed = allowed;
            settle();
          });
        } else settle();
        return;
      }
      if (navigating.current) {
        if (target.index !== committed.current.index)
          window.history.go(committed.current.index - target.index);
        return;
      }
      if (committed.current.pathname !== '/settings' || target.index === committed.current.index) {
        commit(target);
        return;
      }
      navigating.current = true;
      transition = { target, phase: 'restoring' };
      window.history.go(committed.current.index - target.index);
    };
    window.addEventListener('popstate', onPop);
    return () => {
      live = false;
      window.removeEventListener('popstate', onPop);
    };
  }, [commit]);
  if (location.pathname === '/settings')
    return (
      <SettingsPage
        search={location.search}
        onNavigate={navigate}
        onLeaveGuardChange={setLeaveSettings}
        onBack={() => void navigate('/')}
      />
    );
  return (
    <SidebarProvider className="app-shell h-dvh min-h-0 overflow-hidden">
      <SessionSidebar onOpenSettings={() => void navigate('/settings')} />
      <SidebarInset className="workspace min-h-0 min-w-0 overflow-hidden">
        <ChatHeader onOpenSettings={(section = 'general') => void navigate('/settings?tab=' + section)} />
        <ErrorBanner />
        <ChatView key={currentSession?.session_id} />
        <div className="chat-bottom">
          <ChatInput key={currentSession?.session_id} />
          <StatusBar />
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
