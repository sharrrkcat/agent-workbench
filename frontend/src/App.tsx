import { COGITA_CHARACTER_ID } from './types/chat';
import { ResourceEmpty } from './components/settings/resources/ResourceUI';
import { useTranslation } from 'react-i18next';
import { QQSessionDialog } from "./components/characters/QQSessionDialog";
import { QQSessionView } from "./components/characters/QQSessionView";
import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createWebSocketUrl } from './api/url';
import { usePersonasStore } from './store/usePersonasStore';
import { ChatHeader } from './components/ChatHeader';
import { ChatInput } from './components/ChatInput';
import { ChatView } from './components/ChatView';
import { ErrorBanner } from './components/ErrorBanner';
import { SessionSidebar } from './components/SessionSidebar';
import { SettingsPage } from './components/SettingsPage';
import { SidebarInset, SidebarProvider, SidebarTrigger } from './components/ui/sidebar';
import { useCogitaStore } from './store/useCogitaStore';
import { useModelEvents } from './hooks/useModelEvents';
import type { LeaveGuard } from './components/settings/resources/ResourceUI';
import { readSettingsRoute, settingsRouteUrl } from './components/settings/navigation';
import { CharacterPage } from './components/characters/CharacterPage';
import { QQResourcesPage } from './components/characters/QQResourcesPage';
import { PlaygroundPage } from './components/playground/PlaygroundPage';
import { readPlaygroundRoute } from './components/playground/navigation';
import { isDraftRoute, isCharacterSettingsRoute, isResourcesRoute, newChatUrl, characterUrl, readCharacterRoute } from './components/characters/navigation';
import { useCharactersStore } from './store/useCharactersStore';
import { ResourceLoading, errorText } from './components/settings/resources/ResourceUI';

const FarklePage = lazy(() => import('./components/playground/farkle/FarklePage'));

type Location = { pathname: string; search: string; url: string; index: number };
const readLocation = (): Location => ({
  pathname: window.location.pathname,
  search: window.location.search,
  url: window.location.pathname + window.location.search + window.location.hash,
  index: window.history.state?.cogitaIndex ?? 0,
});
const guarded = (location: Location) => location.pathname === '/settings' || isCharacterSettingsRoute(location) || isResourcesRoute(location);
const conversationRoute = (location: Location) => location.pathname !== '/settings' && !readPlaygroundRoute(location)
  && !isResourcesRoute(location) && !isCharacterSettingsRoute(location);

export default function App() {
  const { t } = useTranslation('personas');
  useModelEvents();
  const initialize = useCogitaStore((state) => state.initialize);
  const currentSession = useCogitaStore((state) => state.currentSession);
  const sessionLoad = useCogitaStore((state) => state.sessionLoad);
  const chatDraft = useCogitaStore((state) => state.chatDraft);
  const sessionEpoch = useCogitaStore((state) => state.sessionEpoch);
  const initialized = useCogitaStore((state) => state.initialized);
  const error = useCogitaStore((state) => state.error);
  const activateLocation = useCogitaStore((state) => state.activateLocation);
  const refreshCurrent = useCogitaStore((state) => state.refreshCurrent);
  const applyRuntimeEvent = useCogitaStore((state) => state.applyRuntimeEvent);
  const [qqCreate, setQQCreate] = useState<string | null>(null);
  const [location, setLocation] = useState(readLocation);
  const committed = useRef(location);
  const lastHome = useRef(location.pathname === '/settings' ? '/' : location.url);
  const navigating = useRef(false);
  const leaveSettings = useRef<LeaveGuard>(async () => true);
  const draftEpoch = useRef<number | null>(null);
  const socketSession = useRef<string | null>(null);
  const setLeaveSettings = useCallback((guard: LeaveGuard) => {
    leaveSettings.current = guard;
  }, []);
  const commit = useCallback((next: Location) => {
    committed.current = next;
    useCogitaStore.getState().setConversationVisible(conversationRoute(next));
    if (readPlaygroundRoute(next)) useCogitaStore.getState().deactivateConversation();
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
    void initialize(false);
  }, [initialize]);
  useLayoutEffect(() => {
    useCogitaStore.getState().setConversationVisible(conversationRoute(location));
    if (!initialized || location.pathname === '/settings' || readPlaygroundRoute(location)) return;
    const route = readCharacterRoute(location);
    if (isCharacterSettingsRoute(location) || isResourcesRoute(location)) {
      useCogitaStore.getState().deactivateConversation();
      if (route.characterId) void useCharactersStore.getState().load(route.characterId)
        .catch((reason) => useCogitaStore.getState().setError(errorText(reason)));
    } else if (isDraftRoute(location)) void useCogitaStore.getState().startDraft(route.characterId);
    else void activateLocation(route.characterId, route.sessionId);
  }, [initialized, location.pathname, location.search, activateLocation]);

  useEffect(() => {
    if (chatDraft) { draftEpoch.current = sessionEpoch; return; }
    if (draftEpoch.current !== sessionEpoch) return;
    if (!isDraftRoute(location) || !currentSession || useCogitaStore.getState().currentSession?.session_id !== currentSession.session_id ||
        currentSession.character_id !== readCharacterRoute(location).characterId) return;
    const url = currentSession.character_id ? characterUrl(currentSession.character_id, currentSession.session_id) : '/';
    window.history.replaceState({ cogitaIndex: committed.current.index }, '', url);
    commit(readLocation());
    draftEpoch.current = null;
  }, [chatDraft, sessionEpoch, currentSession?.session_id, location, commit]);

  const selectSession = useCallback(async (id: string, characterId: string | null) => {
    if (navigating.current) return false;
    const origin = committed.current;
    const url = characterUrl(characterId ?? COGITA_CHARACTER_ID, id);
    if (guarded(committed.current) && !(await leaveSettings.current(new URL(url, window.location.href)))) return false;
    if (committed.current !== origin) return false;
    commitUrl(url);
    void useCogitaStore.getState().selectSession(id, characterId);
    return true;
  }, [commitUrl]);
  const createSession = useCallback(async (characterId: string | null = null) => {
    if (navigating.current) return false;
    const origin = committed.current;
    characterId = characterId ?? COGITA_CHARACTER_ID;
    const target = newChatUrl(characterId);
    if (guarded(committed.current) && !(await leaveSettings.current(new URL(target, window.location.href)))) return false;
    if (committed.current !== origin) return false;
    if (characterId && useCharactersStore.getState().characters.find((p) => p.id === characterId)?.kind === 'qqbot') {
      setQQCreate(characterId);
      return true;
    }
    await useCogitaStore.getState().startDraft(characterId);
    if (committed.current !== origin || useCogitaStore.getState().chatDraft?.character_id !== characterId) return false;
    commitUrl(target);
    return true;
  }, [commitUrl]);
  const sessionDeleted = useCallback((id: string) => {
    const route = readCharacterRoute(committed.current);
    if (route.characterId && route.sessionId === id) {
      const selected = useCogitaStore.getState().currentSession;
      const draft = useCogitaStore.getState().chatDraft;
      commitUrl(draft?.character_id === route.characterId ? newChatUrl(route.characterId) : characterUrl(route.characterId, selected?.character_id === route.characterId ? selected.session_id : null));
    }
  }, [commitUrl]);
  const characterDeleted = useCallback((id: string) => {
    if (readCharacterRoute(committed.current).characterId === id) {
      leaveSettings.current = async () => true;
      commitUrl('/');
    }
  }, [commitUrl]);
  useEffect(() => {
    if (!conversationRoute(location) || !currentSession || (sessionLoad && sessionLoad.status !== 'ready')) return;
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
        const first = socketSession.current !== currentSession!.session_id;
        socketSession.current = currentSession!.session_id;
        if (currentSession!.kind !== 'qqbot' || !first) {
          void refreshCurrent();
          void usePersonasStore.getState().reload().catch((reason) => useCogitaStore.getState().setError(errorText(reason)));
        }
        next();
      });
      socket.addEventListener('message', (event) => {
        if (closed || useCogitaStore.getState().sessionEpoch !== sessionEpoch) return;
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
  }, [currentSession?.session_id, sessionLoad?.status, sessionEpoch, location.pathname, location.search, applyRuntimeEvent, refreshCurrent]);
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
  const characterRoute = readCharacterRoute(location);
  const activeCharacter = useCharactersStore((state) => state.characters.find((item) => item.id === characterRoute.characterId));
  const playgroundRoute = readPlaygroundRoute(location);
  const conversationReady = !!currentSession && currentSession.character_id === characterRoute.characterId &&
    (!characterRoute.sessionId || isDraftRoute(location) || currentSession.session_id === characterRoute.sessionId);
  const draftReady = !!chatDraft && chatDraft.character_id === characterRoute.characterId &&
    (isDraftRoute(location) || !characterRoute.sessionId);
  return (
    <SidebarProvider className="app-shell h-dvh min-h-0 overflow-hidden">
      {location.pathname === '/settings' ? (
        <SettingsPage search={location.search} onNavigate={navigate} onLeaveGuardChange={setLeaveSettings} returnTo={lastHome.current} />
      ) : playgroundRoute === 'farkle' ? (
        <Suspense fallback={<SidebarInset className="workspace min-h-0 min-w-0"><ResourceLoading /></SidebarInset>}>
          <FarklePage search={location.search} onNavigate={navigate} />
        </Suspense>
      ) : (
        <>
          <SessionSidebar onOpenSettings={() => navigate('/settings')} onNavigate={navigate}
            playgroundActive={playgroundRoute !== null}
            resourcesCharacterId={isResourcesRoute(location) ? characterRoute.characterId : null}
            onSelectSession={selectSession} onCreateSession={createSession} onSessionDeleted={sessionDeleted} onCharacterDeleted={characterDeleted} />
          <SidebarInset className="workspace min-h-0 min-w-0 overflow-hidden">
            {playgroundRoute ? <PlaygroundPage onNavigate={navigate} /> :
            characterRoute.characterId && isResourcesRoute(location) ?
              <QQResourcesPage key={characterRoute.characterId} characterId={characterRoute.characterId} search={location.search}
                onNavigate={navigate} onLeaveGuardChange={setLeaveSettings} /> :
            characterRoute.characterId && isCharacterSettingsRoute(location) ?
              <CharacterPage characterId={characterRoute.characterId} onNavigate={navigate} onLeaveGuardChange={setLeaveSettings} onCreateSession={createSession} /> :
              activeCharacter?.kind === 'qqbot' && !currentSession && !sessionLoad ? <>
                <header className="topbar"><SidebarTrigger /><h1 className="chat-title">{activeCharacter.name}</h1></header>
                <ResourceEmpty>{t('qq.emptyConversations')}</ResourceEmpty>
              </> :
              currentSession?.kind === 'qqbot' && conversationReady ? <QQSessionView key={currentSession.session_id} session={currentSession} /> : <>
                <ChatHeader onOpenSettings={(route) => void navigate(settingsRouteUrl(route))} />
                <ErrorBanner />
                {conversationReady || draftReady || sessionLoad ? <ChatView key={sessionEpoch} /> :
                <div className="min-h-0 flex-1"><ResourceLoading key={sessionEpoch} error={error || undefined} retry={() => {
                  if (isDraftRoute(location)) void useCogitaStore.getState().startDraft(characterRoute.characterId);
                  else void activateLocation(characterRoute.characterId, characterRoute.sessionId);
                }} /></div>}
                <div className="chat-bottom"><ChatInput /></div>
              </>}
          </SidebarInset>
        </>
      )}
      {qqCreate ? <QQSessionDialog characterId={qqCreate} onClose={() => setQQCreate(null)} onSaved={(id) => {
        const characterId = qqCreate; setQQCreate(null); void selectSession(id, characterId);
      }} /> : null}
    </SidebarProvider>
  );
}
