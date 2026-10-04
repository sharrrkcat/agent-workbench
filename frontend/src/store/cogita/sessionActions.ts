import type { CogitaActions, CogitaState } from './state';
import type { Session } from '../../types/chat';
import { errorText } from './mergeState';

import { useModelsStore } from '../useModelsStore';
import { chatApi } from '../../api/chat';
import { settingsApi } from '../../api/settings';
import { projectsApi } from '../../api/projects';
import { useProjectsStore } from '../useProjectsStore';
import { usePersonasStore } from '../usePersonasStore';
import { toolsApi } from '../../api/tools';
import { defaultModelId } from './drafts';
import { historyPageState } from './historyWindow';

function conversation(state: CogitaState, session: Session | null, projectId: string | null): Partial<CogitaState> {
  return {
    currentSession: session, currentProjectId: projectId, chatDraft: null, pendingKnowledge: null,
    sessionLoad: null,
    lastOrdinarySessionId: session?.kind === 'ordinary' ? session.session_id : state.lastOrdinarySessionId,
    messages: [], runs: [], stepsByRunId: {}, historyWindow: null, historyLoading: false, historyFollowing: true, historyAnchor: null, error: null,
    composerDraftText: session ? state.messageQueues[session.session_id]?.editing?.content ?? '' : '', queueTarget: null,
    sessionEpoch: state.sessionEpoch + 1, deletedMessageIds: [], deletedRunIds: [], sending: false, awaitingAcceptance: false, pendingClientMessageId: null, mutatingHistory: false,
  };
}

export const createSessionActions: CogitaActions<
  | 'initialize'
  | 'reloadSessions'
  | 'selectSession'
  | 'retrySession'
  | 'startDraft'
  | 'saveDraft'
  | 'deleteSession'
  | 'updateSession'
  | 'activateLocation'
  | 'forgetProject'
  | 'setError'
> = (set, get) => {
  let initializationVersion = 0;
  async function loadSession(id: string, scope: string | null, epoch: number) {
    let active = true;
    try {
      if (scope && useProjectsStore.getState().projects.find((project) => project.id === scope)?.kind === 'timeline')
        throw new Error('PROJECT_CHAT_UNAVAILABLE: Timeline conversations are not available yet.');
      const sessionRequest = chatApi.getSession(id).then((session) => {
        if (session.project_id !== scope) throw new Error('SESSION_PROJECT_MISMATCH: Session does not belong to this Project.');
        if (active && get().sessionEpoch === epoch) set({ currentSession: session });
        return session;
      });
      const [session, page] = await Promise.all([
        sessionRequest, chatApi.getHistory(id),
        usePersonasStore.getState().reload().catch((error) => {
          if (get().sessionEpoch === epoch) set({ error: errorText(error) });
        }),
        scope ? Promise.resolve(useProjectsStore.getState().projects.find((project) => project.id === scope)
          ?? useProjectsStore.getState().load(scope)).then((project) => {
          if (project.kind === 'timeline') throw new Error('PROJECT_CHAT_UNAVAILABLE: Timeline conversations are not available yet.');
        }) : Promise.resolve(),
      ]);
      if (get().sessionEpoch !== epoch) return;
      set((state) => ({
        ...historyPageState({ ...state, currentSession: session }, page, 'latest'), currentSession: session,
        composerDraftText: state.messageQueues[id]?.editing?.content ?? state.composerDraftText,
        lastOrdinarySessionId: session.kind === 'ordinary' ? id : state.lastOrdinarySessionId,
        sessions: state.sessions.some((item) => item.session_id === id)
          ? state.sessions.map((item) => item.session_id === id ? session : item) : [...state.sessions, session],
        messageVersion: state.messageVersion + 1, runVersion: state.runVersion + 1, sessionVersion: state.sessionVersion + 1,
      }));
      await get().reconcileMessageQueue(id);
      if (get().sessionEpoch === epoch) set({ sessionLoad: { sessionId: id, projectId: scope, status: 'ready', error: null } });
    } catch (error) {
      if (get().sessionEpoch === epoch)
        set({ sessionLoad: { sessionId: id, projectId: scope, status: 'error', error: errorText(error) } });
    } finally {
      active = false;
    }
  }
  return ({
  initialize: async (selectOrdinary = true) => {
    const request = ++initializationVersion;
    const epoch = get().sessionEpoch + 1;
    const settingsVersion = get().settingsVersion;
    set({ loading: true, error: null, sessionEpoch: epoch });
    try {
      const [listed, settings] = await Promise.all([
        chatApi.listSessions(), settingsApi.getGeneralSettings(), useModelsStore.getState().reload(),
      ]);
      if (request !== initializationVersion) return;
      const sessions = listed;
      const selected = selectOrdinary ? sessions[0] : null;
      set((state) => ({ sessions: [...state.sessions.filter((session) => session.kind !== 'ordinary'), ...sessions] }));
      if (get().settingsVersion === settingsVersion) get().setSettings(settings);
      if (get().sessionEpoch === epoch) {
        if (selectOrdinary && !selected) await get().startDraft();
        else if (selected) await get().selectSession(selected.session_id, null);
      }
    } catch (error) {
      if (get().sessionEpoch === epoch) set({ error: errorText(error) });
    } finally {
      if (request === initializationVersion) set({ loading: false, initialized: true });
    }
  },

  reloadSessions: async (projectId = null) => {
    const version = get().sessionVersion;
    const sessions = projectId ? await projectsApi.listSessions(projectId) : await chatApi.listSessions();
    if (version === get().sessionVersion)
      set((state) => ({ sessions: [...state.sessions.filter((session) => session.project_id !== projectId), ...sessions] }));
    await get().refreshCurrent();
  },

  selectSession: async (id, projectId) => {
    const cached = get().sessions.find((item) => item.session_id === id);
    const scope = projectId === undefined ? cached?.project_id ?? null : projectId;
    const active = get().sessionLoad;
    if (active?.sessionId === id && active.projectId === scope) return;
    if (!active && !get().chatDraft && get().currentSession?.session_id === id && get().currentProjectId === scope) return;
    set((state) => ({ ...conversation(state, cached?.project_id === scope ? cached : null, scope),
      sessionLoad: { sessionId: id, projectId: scope, status: 'loading', error: null } }));
    await loadSession(id, scope, get().sessionEpoch);
  },

  retrySession: async () => {
    const target = get().sessionLoad;
    if (target?.status !== 'error') return;
    set({ sessionLoad: { ...target, status: 'loading', error: null } });
    await loadSession(target.sessionId, target.projectId, get().sessionEpoch);
  },

  startDraft: async (projectId = null) => {
    if (get().chatDraft?.project_id === projectId) return;
    set((state) => conversation(state, null, projectId));
    const epoch = get().sessionEpoch;
    try {
      const [, tools, project] = await Promise.all([
        usePersonasStore.getState().reload(), toolsApi.listTools(),
        projectId ? useProjectsStore.getState().load(projectId) : Promise.resolve(null),
        useModelsStore.getState().reload(),
      ]);
      if (get().sessionEpoch !== epoch) return;
      if (project && project.kind !== 'workspace') throw new Error('PROJECT_CHAT_UNAVAILABLE: Timeline conversations are not available yet.');
      const personas = usePersonasStore.getState().personas;
      const user = personas.find((p) => p.collection === 'user')!;
      const base = { title: '', user_persona: { id: user.id, name: user.name, avatar_attachment_id: user.avatar_attachment_id }, knowledge_base_ids: [] };
      const models = useModelsStore.getState();
      set({ chatDraft: project ? { ...base, kind: 'workspace', project_id: project.id, overrides: {} }
        : { ...base, kind: 'ordinary', project_id: null,
          persona_id: personas.find((p) => p.collection === 'agent' && p.is_protected)!.id,
          model_profile_id: defaultModelId(models.profiles, models.settings?.default_model_profile_id),
          context_policy: { max_messages: 100, max_chars: 100000, include_attachments: 'explicit' },
          generation: {}, reasoning: true, harness_enabled: false, tools_allowed: tools.filter((tool) => tool.name !== "qq_send_message").map((tool) => tool.name) } });
    } catch (error) {
      if (get().sessionEpoch === epoch) set({ error: errorText(error) });
    }
  },

  saveDraft: (patch, knowledgeIds) => set((state) => {
    const draft = state.chatDraft;
    if (!draft || state.sending) return {};
    return { chatDraft: { ...draft, ...patch,
      ...(draft.kind === 'workspace' && 'overrides' in patch ? { overrides: { ...draft.overrides, ...patch.overrides } } : {}),
      ...(knowledgeIds === undefined ? {} : { knowledge_base_ids: knowledgeIds }) } };
  }),

  deleteSession: async (id) => {
    const projectId = get().sessions.find((session) => session.session_id === id)?.project_id ?? null;
    try {
      await chatApi.deleteSession(id);
      const epoch = get().sessionEpoch;
      set((state) => ({
        sessions: state.sessions.filter((item) => item.session_id !== id),
        messageQueues: Object.fromEntries(Object.entries(state.messageQueues).filter(([sessionId]) => sessionId !== id)),
        sessionVersion: state.sessionVersion + 1,
      }));
      if ((get().sessionLoad?.sessionId ?? get().currentSession?.session_id) === id && get().sessionEpoch === epoch) {
        const next = get().sessions.find((item) => item.project_id === projectId);
        if (next) await get().selectSession(next.session_id, projectId);
        else if (projectId === null) await get().startDraft();
        else set((state) => conversation(state, null, projectId));
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
        currentSession: updated,
        sessions: state.sessions.map((item) => (item.session_id === updated.session_id ? updated : item)),
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

  activateLocation: async (projectId, sessionId = null) => {
    if (projectId === null) {
      if (get().currentProjectId === null && (get().currentSession || get().chatDraft || get().sessionLoad)) return;
      const ordinary = get().sessions.filter((session) => session.kind === 'ordinary');
      const selected = ordinary.find((session) => session.session_id === get().lastOrdinarySessionId) ?? ordinary[0];
      if (selected) await get().selectSession(selected.session_id, null);
      else await get().startDraft();
      return;
    }
    if (sessionId) { await get().selectSession(sessionId, projectId); return; }
    if (!get().sessionLoad && !get().chatDraft && get().currentProjectId === projectId && (get().currentSession?.session_id ?? null) === sessionId &&
        useProjectsStore.getState().projects.some((project) => project.id === projectId)) return;
    set((state) => conversation(state, null, projectId));
    const epoch = get().sessionEpoch;
    try {
      await useProjectsStore.getState().load(projectId);
    } catch (error) {
      if (get().sessionEpoch === epoch) set({ error: errorText(error) });
    }
  },

  forgetProject: (projectId) => set((state) => ({
    sessions: state.sessions.filter((session) => session.project_id !== projectId),
    messageQueues: Object.fromEntries(Object.entries(state.messageQueues).filter(([, queue]) => queue.projectId !== projectId)),
    sessionVersion: state.sessionVersion + 1,
    ...(state.currentProjectId === projectId ? conversation(state, null, null) : {}),
  })),

  setError: (error) => set({ error }),
  });
};
