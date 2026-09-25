import { useCallback, useEffect, useRef, useState } from 'react';
import { createWebSocketUrl } from './api/url';
import { ChatHeader } from './components/ChatHeader';
import { ChatInput } from './components/ChatInput';
import { ChatView } from './components/ChatView';
import { ErrorBanner } from './components/ErrorBanner';
import { SessionSidebar } from './components/SessionSidebar';
import { SettingsPage } from './components/SettingsPage';
import { StatusBar } from './components/StatusBar';
import { SidebarInset, SidebarProvider, SidebarTrigger } from './components/ui/sidebar';
import { useCogitaStore } from './store/useCogitaStore';
import { useModelEvents } from './hooks/useModelEvents';
import type { LeaveGuard } from './components/settings/resources/ResourceUI';
import { readSettingsRoute, settingsRouteUrl } from './components/settings/navigation';
import { ProjectPage } from './components/projects/ProjectPage';
import { projectUrl, readProjectRoute } from './components/projects/navigation';
import { useProjectsStore } from './store/useProjectsStore';
import { ResourceLoading, errorText } from './components/settings/resources/ResourceUI';

type Location = { pathname: string; search: string; url: string; index: number };
const readLocation = (): Location => ({
  pathname: window.location.pathname,
  search: window.location.search,
  url: window.location.pathname + window.location.search + window.location.hash,
  index: window.history.state?.cogitaIndex ?? 0,
});
const guarded = (location: Location) => location.pathname === '/settings' ||
  (!!readProjectRoute(location).projectId && !readProjectRoute(location).sessionId);

export default function App() {
  useModelEvents();
  const initialize = useCogitaStore((state) => state.initialize);
  const currentSession = useCogitaStore((state) => state.currentSession);
  const initialized = useCogitaStore((state) => state.initialized);
  const error = useCogitaStore((state) => state.error);
  const activateLocation = useCogitaStore((state) => state.activateLocation);
  const refreshCurrent = useCogitaStore((state) => state.refreshCurrent);
  const applyRuntimeEvent = useCogitaStore((state) => state.applyRuntimeEvent);
  const [location, setLocation] = useState(readLocation);
  const committed = useRef(location);
  const lastHome = useRef(location.pathname === '/settings' ? '/' : location.url);
  const navigating = useRef(false);
  const leaveSettings = useRef<LeaveGuard>(async () => true);
  const setLeaveSettings = useCallback((guard: LeaveGuard) => {
    leaveSettings.current = guard;
  }, []);
  const commit = useCallback((next: Location) => {
    committed.current = next;
    if (next.pathname !== '/settings') lastHome.current = next.url;
    setLocation(next);
  }, []);
  const commitUrl = useCallback((url: string) => {
    if (url === committed.current.url) return;
    window.history.pushState({ cogitaIndex: committed.current.index + 1 }, '', url);
    commit(readLocation());
  }, [commit]);
  const navigate = useCallback(
    async (url: string) => {
      if (navigating.current) return false;
      navigating.current = true;
      try {
        const target = new URL(url, window.location.href);
        const sameSettingsPage =
          target.pathname === '/settings' &&
          committed.current.pathname === '/settings' &&
          settingsRouteUrl(readSettingsRoute(target.search)) ===
            settingsRouteUrl(readSettingsRoute(committed.current.search));
        const changingRoute = url !== committed.current.url && !sameSettingsPage;
        // Resource pages also use their existing URL to leave a local detail editor.
        if (guarded(committed.current) && (committed.current.pathname === '/settings' || changingRoute) &&
            !(await leaveSettings.current(target))) return false;
        if (!changingRoute) return true;
        commitUrl(url);
        return true;
      } finally {
        navigating.current = false;
      }
    },
    [commitUrl],
  );
  useEffect(() => {
    void initialize(!readProjectRoute(committed.current).projectId);
    void useProjectsStore.getState().reload().catch((reason) => useCogitaStore.getState().setError(errorText(reason)));
  }, [initialize]);
  useEffect(() => {
    if (!initialized || location.pathname === '/settings') return;
    const route = readProjectRoute(location);
    void activateLocation(route.projectId, route.sessionId);
  }, [initialized, location.pathname, location.search, activateLocation]);

  const selectSession = useCallback(async (id: string, projectId: string | null) => {
    if (navigating.current) return false;
    const origin = committed.current;
    const url = projectId ? projectUrl(projectId, id) : '/';
    if (guarded(committed.current) && !(await leaveSettings.current(new URL(url, window.location.href)))) return false;
    await useCogitaStore.getState().selectSession(id, projectId);
    if (committed.current !== origin || useCogitaStore.getState().currentSession?.session_id !== id) return false;
    commitUrl(url);
    return true;
  }, [commitUrl]);
  const createSession = useCallback(async (projectId: string | null = null) => {
    if (navigating.current) return false;
    const origin = committed.current;
    const target = projectId ? projectUrl(projectId) : '/';
    if (guarded(committed.current) && !(await leaveSettings.current(new URL(target, window.location.href)))) return false;
    const session = await useCogitaStore.getState().createSession(projectId);
    if (committed.current !== origin || !session || useCogitaStore.getState().currentSession?.session_id !== session.session_id) return false;
    commitUrl(projectId ? projectUrl(projectId, session.session_id) : '/');
    return true;
  }, [commitUrl]);
  const sessionDeleted = useCallback((id: string) => {
    const route = readProjectRoute(committed.current);
    if (route.projectId && route.sessionId === id) {
      const selected = useCogitaStore.getState().currentSession;
      commitUrl(projectUrl(route.projectId, selected?.project_id === route.projectId ? selected.session_id : null));
    }
  }, [commitUrl]);
  const projectDeleted = useCallback((id: string) => {
    if (readProjectRoute(committed.current).projectId === id) {
      leaveSettings.current = async () => true;
      commitUrl('/');
    }
  }, [commitUrl]);
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
      if (!guarded(committed.current) || target.index === committed.current.index) {
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
  const projectRoute = readProjectRoute(location);
  const conversationReady = !!currentSession && currentSession.project_id === projectRoute.projectId &&
    (!projectRoute.projectId || currentSession.session_id === projectRoute.sessionId);
  return (
    <SidebarProvider className="app-shell h-dvh min-h-0 overflow-hidden">
      {location.pathname === '/settings' ? (
        <SettingsPage search={location.search} onNavigate={navigate} onLeaveGuardChange={setLeaveSettings} returnTo={lastHome.current} />
      ) : (
        <>
          <SessionSidebar onOpenSettings={() => navigate('/settings')} onNavigate={navigate}
            onSelectSession={selectSession} onCreateSession={createSession} onSessionDeleted={sessionDeleted} onProjectDeleted={projectDeleted} />
          <SidebarInset className="workspace min-h-0 min-w-0 overflow-hidden">
            {projectRoute.projectId && !projectRoute.sessionId ?
              <ProjectPage projectId={projectRoute.projectId} onNavigate={navigate} onLeaveGuardChange={setLeaveSettings} onCreateSession={createSession} /> :
              conversationReady ? <>
                <ChatHeader onOpenSettings={(route) => void navigate(settingsRouteUrl(route))} />
                <ErrorBanner />
                <ChatView key={currentSession.session_id} />
                <div className="chat-bottom"><ChatInput key={currentSession.session_id} /><StatusBar /></div>
              </> : <>
                <header className="topbar"><SidebarTrigger /></header>
                <ResourceLoading error={error || undefined} retry={() => void activateLocation(projectRoute.projectId, projectRoute.sessionId)} />
              </>}
          </SidebarInset>
        </>
      )}
    </SidebarProvider>
  );
}
