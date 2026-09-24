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
import { useCogitaStore } from './store/useCogitaStore';
import { useModelEvents } from './hooks/useModelEvents';
import type { LeaveGuard } from './components/settings/resources/ResourceUI';
import { readSettingsRoute, settingsRouteUrl } from './components/settings/navigation';

type Location = { pathname: string; search: string; url: string; index: number };
const readLocation = (): Location => ({
  pathname: window.location.pathname,
  search: window.location.search,
  url: window.location.pathname + window.location.search + window.location.hash,
  index: window.history.state?.cogitaIndex ?? 0,
});

export default function App() {
  useModelEvents();
  const initialize = useCogitaStore((state) => state.initialize);
  const currentSession = useCogitaStore((state) => state.currentSession);
  const refreshCurrent = useCogitaStore((state) => state.refreshCurrent);
  const applyRuntimeEvent = useCogitaStore((state) => state.applyRuntimeEvent);
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
    async (url: string) => {
      if (navigating.current) return false;
      navigating.current = true;
      try {
        const target = new URL(url, window.location.href);
        if (committed.current.pathname === '/settings' && !(await leaveSettings.current(target)))
          return false;
        const sameSettingsPage =
          target.pathname === '/settings' &&
          committed.current.pathname === '/settings' &&
          settingsRouteUrl(readSettingsRoute(target.search)) ===
            settingsRouteUrl(readSettingsRoute(committed.current.search));
        if (url === committed.current.url || sameSettingsPage) return true;
        const index = committed.current.index + 1;
        window.history.pushState({ cogitaIndex: index }, '', url);
        commit(readLocation());
        return true;
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
    window.history.replaceState({ cogitaIndex: committed.current.index }, '', committed.current.url);
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
          void leaveSettings.current(current.target).then((allowed) => {
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
  return (
    <SidebarProvider className="app-shell h-dvh min-h-0 overflow-hidden">
      {location.pathname === '/settings' ? (
        <SettingsPage search={location.search} onNavigate={navigate} onLeaveGuardChange={setLeaveSettings} />
      ) : (
        <>
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
        </>
      )}
    </SidebarProvider>
  );
}
