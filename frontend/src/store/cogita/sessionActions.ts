import type { CogitaActions, CogitaState } from './state';
import type { Session } from '../../types/chat';
import { COGITA_CHARACTER_ID } from '../../types/chat';
import { errorText } from './mergeState';
import { useModelsStore } from '../useModelsStore';
import { chatApi } from '../../api/chat';
import { settingsApi } from '../../api/settings';
import { charactersApi } from '../../api/characters';
import { useCharactersStore } from '../useCharactersStore';
import { usePersonasStore } from '../usePersonasStore';
import { historyPageState } from './historyWindow';

const selectionKey = (characterId: string) => 'cogita.lastSession.' + characterId;
export function rememberSession(session: Session) {
  if (typeof localStorage !== 'undefined') localStorage.setItem(selectionKey(session.character_id), session.session_id);
}
function lastSession(characterId: string) {
  return typeof localStorage === 'undefined' ? null : localStorage.getItem(selectionKey(characterId));
}
function forgetSelection(characterId: string) {
  if (typeof localStorage !== 'undefined') localStorage.removeItem(selectionKey(characterId));
}

function conversation(state: CogitaState, session: Session | null, characterId: string | null): Partial<CogitaState> {
  return {
    currentSession: session, currentCharacterId: characterId, chatDraft: null, sessionLoad: null,
    messages: [], runs: [], stepsByRunId: {}, historyWindow: null, historyLoading: false, historyFollowing: true, historyAnchor: null, error: null,
    composerDraftText: session ? state.messageQueues[session.session_id]?.editing?.content ?? '' : '', queueTarget: null,
    sessionEpoch: state.sessionEpoch + 1, deletedMessageIds: [], deletedRunIds: [], sending: false,
    awaitingAcceptance: false, pendingClientMessageId: null, mutatingHistory: false,
  };
}

export const createSessionActions: CogitaActions<
  'initialize' | 'reloadSessions' | 'selectSession' | 'retrySession' | 'startDraft' | 'saveDraft' |
  'deleteSession' | 'updateSession' | 'activateLocation' | 'deactivateConversation' | 'forgetCharacter' | 'setError'
> = (set, get, store) => {
  let initializationVersion = 0;
  let controller: AbortController | null = null;
  store.subscribe((state, previous) => {
    if (!state.conversationVisible || state.sessionEpoch !== previous.sessionEpoch) controller?.abort();
  });
  async function loadSession(id: string, scope: string, epoch: number) {
    controller?.abort();
    const request = new AbortController(); controller = request;
    try {
      const owner = useCharactersStore.getState().characters.find((item) => item.id === scope);
      const sessionRequest = chatApi.getSession(id, request.signal).then((session) => {
        if (session.character_id !== scope) throw new Error('SESSION_CHARACTER_MISMATCH: Session does not belong to this Character.');
        if (!request.signal.aborted && get().sessionEpoch === epoch) set({ currentSession: session });
        return session;
      });
      const history = owner?.kind === 'qqbot' ? Promise.resolve(null) : owner
        ? chatApi.getHistory(id, {}, request.signal)
        : sessionRequest.then((session) => session.kind === 'qqbot' || request.signal.aborted ? null : chatApi.getHistory(id, {}, request.signal));
      const [session, page] = await Promise.all([
        sessionRequest, history, owner ? Promise.resolve(owner) : useCharactersStore.getState().load(scope),
      ]);
      if (request.signal.aborted || get().sessionEpoch !== epoch) return;
      if (session.kind === 'normal') await usePersonasStore.getState().reload().catch((error) => {
        if (!request.signal.aborted && get().sessionEpoch === epoch) set({ error: errorText(error) });
      });
      if (request.signal.aborted || get().sessionEpoch !== epoch) return;
      rememberSession(session);
      set((state) => ({
        ...(page ? historyPageState({ ...state, currentSession: session }, page, 'latest') : {}), currentSession: session,
        composerDraftText: state.messageQueues[id]?.editing?.content ?? state.composerDraftText,
        sessions: state.sessions.some((item) => item.session_id === id)
          ? state.sessions.map((item) => item.session_id === id ? session : item) : [...state.sessions, session],
        messageVersion: state.messageVersion + 1, runVersion: state.runVersion + 1, sessionVersion: state.sessionVersion + 1,
      }));
      if (session.kind === 'normal') await get().reconcileMessageQueue(id);
      if (get().sessionEpoch === epoch) set({ sessionLoad: { sessionId: id, characterId: scope, status: 'ready', error: null } });
    } catch (error) {
      if (!request.signal.aborted && get().sessionEpoch === epoch) {
        request.abort();
        set({ sessionLoad: { sessionId: id, characterId: scope, status: 'error', error: errorText(error) } });
      }
    } finally {
      if (controller === request) controller = null;
    }
  }
  return {
    initialize: async (selectDefault = true) => {
      const request = ++initializationVersion;
      const epoch = get().sessionEpoch + 1;
      const settingsVersion = get().settingsVersion;
      set({ loading: true, error: null, sessionEpoch: epoch });
      void useModelsStore.getState().reloadProfiles().catch((error) => set({ error: errorText(error) }));
      void useModelsStore.getState().reloadProviders().catch((error) => set({ error: errorText(error) }));
      void useModelsStore.getState().reloadSettings().catch((error) => set({ error: errorText(error) }));
      try {
        const [settings] = await Promise.all([settingsApi.getGeneralSettings(), useCharactersStore.getState().reload()]);
        if (request !== initializationVersion) return;
        if (get().settingsVersion === settingsVersion) get().setSettings(settings);
        if (selectDefault && get().sessionEpoch === epoch && get().conversationVisible)
          await get().activateLocation(COGITA_CHARACTER_ID);
      } catch (error) {
        if (get().sessionEpoch === epoch) set({ error: errorText(error) });
      } finally {
        if (request === initializationVersion) set({ loading: false, initialized: true });
      }
    },

    reloadSessions: async (characterId = COGITA_CHARACTER_ID) => {
      const scope = characterId ?? COGITA_CHARACTER_ID;
      const version = get().sessionVersion;
      const sessions = await charactersApi.listSessions(scope);
      if (version === get().sessionVersion)
        set((state) => ({ sessions: [...state.sessions.filter((session) => session.character_id !== scope), ...sessions] }));
      await get().refreshCurrent();
    },

    selectSession: async (id, characterId) => {
      const cached = get().sessions.find((item) => item.session_id === id);
      const scope = characterId ?? cached?.character_id ?? COGITA_CHARACTER_ID;
      const active = get().sessionLoad;
      if (active?.sessionId === id && active.characterId === scope) return;
      if (!active && !get().chatDraft && get().currentSession?.session_id === id && get().currentCharacterId === scope) return;
      set((state) => ({ ...conversation(state, cached?.character_id === scope ? cached : null, scope),
        sessionLoad: { sessionId: id, characterId: scope, status: 'loading', error: null } }));
      await loadSession(id, scope, get().sessionEpoch);
    },

    retrySession: async () => {
      const target = get().sessionLoad;
      if (target?.status !== 'error') return;
      set({ sessionLoad: { ...target, status: 'loading', error: null } });
      await loadSession(target.sessionId, target.characterId, get().sessionEpoch);
    },

    startDraft: async (characterId = COGITA_CHARACTER_ID) => {
      const scope = characterId ?? COGITA_CHARACTER_ID;
      if (get().chatDraft?.character_id === scope) return;
      set((state) => conversation(state, null, scope));
      const epoch = get().sessionEpoch;
      try {
        const [character] = await Promise.all([
          useCharactersStore.getState().load(scope), usePersonasStore.getState().reload(),
          useModelsStore.getState().reloadProfiles(),
        ]);
        if (get().sessionEpoch !== epoch) return;
        if (character.kind !== 'normal') throw new Error('CHARACTER_KIND_INVALID: QQ conversations require a group or friend binding.');
        set({ chatDraft: { title: '', kind: 'normal', character_id: scope, overrides: {} } });
      } catch (error) {
        if (get().sessionEpoch === epoch) set({ error: errorText(error) });
      }
    },

    saveDraft: (patch) => set((state) => {
      const draft = state.chatDraft;
      if (!draft || state.sending) return {};
      return { chatDraft: { ...draft, ...patch, overrides: { ...draft.overrides, ...patch.overrides } } };
    }),

    deleteSession: async (id) => {
      const session = get().sessions.find((item) => item.session_id === id);
      const scope = session?.character_id;
      const epoch = get().sessionEpoch;
      try {
        await chatApi.deleteSession(id);
        if (scope && lastSession(scope) === id) forgetSelection(scope);
        set((state) => ({
          sessions: state.sessions.filter((item) => item.session_id !== id),
          messageQueues: Object.fromEntries(Object.entries(state.messageQueues).filter(([sessionId]) => sessionId !== id)),
          sessionVersion: state.sessionVersion + 1,
        }));
        if (scope && (get().sessionLoad?.sessionId ?? get().currentSession?.session_id) === id && get().sessionEpoch === epoch) {
          const next = get().sessions.find((item) => item.character_id === scope);
          if (next) await get().selectSession(next.session_id, scope);
          else if (session.kind === 'normal') await get().startDraft(scope);
          else set((state) => conversation(state, null, scope));
        }
      } catch (error) {
        set({ error: errorText(error) });
      }
    },

    updateSession: async (patch) => {
      if (get().sending || (get().sessionLoad && get().sessionLoad?.status !== 'ready')) return false;
      const session = get().currentSession;
      if (!session) {
        if (!get().chatDraft) return false;
        get().saveDraft(patch);
        return true;
      }
      if (get().savingSessionIds.includes(session.session_id)) return false;
      const epoch = get().sessionEpoch;
      set((state) => ({ error: null, savingSessionIds: [...state.savingSessionIds, session.session_id] }));
      try {
        const updated = await chatApi.updateSession(session.session_id, patch);
        if (get().currentSession?.session_id !== updated.session_id || get().sessionEpoch !== epoch) return false;
        set((state) => ({
          currentSession: updated, sessions: state.sessions.map((item) => item.session_id === updated.session_id ? updated : item),
          sessionVersion: state.sessionVersion + 1,
        }));
        return true;
      } catch (error) {
        if (get().sessionEpoch === epoch) set({ error: errorText(error) });
        return false;
      } finally {
        set((state) => ({ savingSessionIds: state.savingSessionIds.filter((id) => id !== session.session_id) }));
      }
    },

    deactivateConversation: () => set((state) => conversation(state, null, null)),

    activateLocation: async (characterId, sessionId = null) => {
      const scope = characterId ?? COGITA_CHARACTER_ID;
      if (sessionId) { await get().selectSession(sessionId, scope); return; }
      if (get().currentCharacterId === scope && (get().currentSession || get().chatDraft || get().sessionLoad)) return;
      set((state) => conversation(state, null, scope));
      const epoch = get().sessionEpoch;
      const version = get().sessionVersion;
      try {
        const [character, sessions] = await Promise.all([
          useCharactersStore.getState().load(scope), charactersApi.listSessions(scope),
        ]);
        if (get().sessionEpoch !== epoch) return;
        if (get().sessionVersion === version)
          set((state) => ({ sessions: [...state.sessions.filter((item) => item.character_id !== scope), ...sessions] }));
        const available = get().sessions.filter((item) => item.character_id === scope)
          .sort((a, b) => b.updated_at.localeCompare(a.updated_at) || b.session_id.localeCompare(a.session_id));
        const selected = available.find((item) => item.session_id === lastSession(scope)) ?? available[0];
        if (selected) await get().selectSession(selected.session_id, scope);
        else if (character.kind === 'normal') await get().startDraft(scope);
      } catch (error) {
        if (get().sessionEpoch === epoch) set({ error: errorText(error) });
      }
    },

    forgetCharacter: (characterId) => {
      forgetSelection(characterId);
      set((state) => ({
        sessions: state.sessions.filter((session) => session.character_id !== characterId),
        messageQueues: Object.fromEntries(Object.entries(state.messageQueues).filter(([, queue]) => queue.characterId !== characterId)),
        sessionVersion: state.sessionVersion + 1,
        ...(state.currentCharacterId === characterId ? conversation(state, null, null) : {}),
      }));
    },

    setError: (error) => set({ error }),
  };
};
