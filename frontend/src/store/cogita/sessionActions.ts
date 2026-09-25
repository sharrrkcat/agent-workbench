import type { CogitaActions, CogitaState } from './state';
import type { Session } from '../../types/chat';
import { errorText, mergeMessages, mergeRuns, mergeSteps, retainedMessages, terminal } from './mergeState';

import { useModelsStore } from '../useModelsStore';
import { chatApi } from '../../api/chat';
import { settingsApi } from '../../api/settings';
import { runsApi } from '../../api/runs';
import { projectsApi } from '../../api/projects';
import { useProjectsStore } from '../useProjectsStore';

function conversation(state: CogitaState, session: Session | null, projectId: string | null): Partial<CogitaState> {
  return {
    currentSession: session, currentProjectId: projectId,
    lastOrdinarySessionId: session?.kind === 'ordinary' ? session.session_id : state.lastOrdinarySessionId,
    messages: [], runs: [], stepsByRunId: {}, error: null, sourceMessageId: null, composerDraftText: '',
    sessionEpoch: state.sessionEpoch + 1, deletedMessageIds: [], deletedRunIds: [], sending: false, mutatingHistory: false,
  };
}

export const createSessionActions: CogitaActions<
  | 'initialize'
  | 'refreshCurrent'
  | 'reloadSessions'
  | 'selectSession'
  | 'createSession'
  | 'deleteSession'
  | 'updateSession'
  | 'activateLocation'
  | 'forgetProject'
  | 'setError'
> = (set, get) => {
  let initializationVersion = 0;
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
      let sessions = listed;
      if (get().sessionEpoch === epoch && selectOrdinary && sessions.length === 0) sessions = [await chatApi.createSession()];
      if (request !== initializationVersion) return;
      const selected = selectOrdinary ? sessions[0] : null;
      set((state) => ({ sessions: [...state.sessions.filter((session) => session.kind === 'workspace'), ...sessions],
        ...(state.sessionEpoch === epoch ? { currentSession: selected, lastOrdinarySessionId: selected?.session_id ?? null } : {}) }));
      if (get().settingsVersion === settingsVersion) get().setSettings(settings);
      if (get().sessionEpoch === epoch) await get().refreshCurrent();
    } catch (error) {
      if (get().sessionEpoch === epoch) set({ error: errorText(error) });
    } finally {
      if (request === initializationVersion) set({ loading: false, initialized: true });
    }
  },

  refreshCurrent: async () => {
    const session = get().currentSession;
    if (!session) return;
    const version = get().messageVersion;
    const runVersion = get().runVersion;
    const sessionVersion = get().sessionVersion;
    const epoch = get().sessionEpoch;
    try {
      const [freshSession, messages, runs] = await Promise.all([
        chatApi.getSession(session.session_id),
        chatApi.listMessages(session.session_id),
        runsApi.listRuns(session.session_id),
      ]);
      if (get().currentSession?.session_id !== session.session_id || get().sessionEpoch !== epoch) return;
      set((state) => ({
        currentSession: state.sessionVersion === sessionVersion ? freshSession : state.currentSession,
        sessions:
          state.sessionVersion === sessionVersion
            ? state.sessions.map((item) => (item.session_id === freshSession.session_id ? freshSession : item))
            : state.sessions,
        messages:
          state.messageVersion !== version
            ? mergeMessages(retainedMessages(state, messages), state.messages)
            : mergeMessages(
                state.messages.filter(
                  (m) => m.metadata?.streaming && runs.some((r) => r.run_id === m.run_id && !terminal(r.status)),
                ),
                retainedMessages(state, messages),
              ),
        runs: mergeRuns(state.runVersion === runVersion ? state.runs.filter((run) => runs.some((fresh) => fresh.run_id === run.run_id)) : state.runs,
          runs.filter((run) => !state.deletedRunIds.includes(run.run_id))),
        stepsByRunId: mergeSteps(
          state.runVersion === runVersion ? Object.fromEntries(Object.entries(state.stepsByRunId).filter(([id]) => runs.some((run) => run.run_id === id))) : state.stepsByRunId,
          runs.filter((run) => !state.deletedRunIds.includes(run.run_id)).flatMap((run) => run.steps || []),
        ),
        messageVersion: state.messageVersion + 1,
        runVersion: state.runVersion + 1,
        sessionVersion: state.sessionVersion + 1,
      }));
    } catch (error) {
      if (get().sessionEpoch === epoch) set({ error: errorText(error) });
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
    set((state) => conversation(state, cached?.project_id === scope ? cached : null, scope));
    const epoch = get().sessionEpoch;
    try {
      const session = cached ?? await chatApi.getSession(id);
      if (get().sessionEpoch !== epoch) return;
      if (session.project_id !== scope) throw new Error('SESSION_PROJECT_MISMATCH: Session does not belong to this Project.');
      set((state) => ({ currentSession: session,
        lastOrdinarySessionId: session.kind === 'ordinary' ? session.session_id : state.lastOrdinarySessionId,
        sessions: state.sessions.some((item) => item.session_id === session.session_id)
          ? state.sessions.map((item) => item.session_id === session.session_id ? session : item)
          : [...state.sessions, session] }));
      await get().refreshCurrent();
    } catch (error) {
      if (get().sessionEpoch === epoch) set({ currentSession: null, error: errorText(error) });
    }
  },

  createSession: async (projectId = null) => {
    const epoch = get().sessionEpoch;
    try {
      const session = projectId ? await projectsApi.createSession(projectId) : await chatApi.createSession();
      set((state) => ({
        sessions: [session, ...state.sessions.filter((item) => item.session_id !== session.session_id)],
        sessionVersion: state.sessionVersion + 1,
        ...(state.sessionEpoch === epoch ? conversation(state, session, projectId) : {}),
      }));
      return session;
    } catch (error) {
      if (get().sessionEpoch === epoch) set({ error: errorText(error) });
    }
  },

  deleteSession: async (id) => {
    const projectId = get().sessions.find((session) => session.session_id === id)?.project_id ?? null;
    try {
      await chatApi.deleteSession(id);
      const epoch = get().sessionEpoch;
      const remaining = get().sessions.filter((item) => item.session_id !== id && item.project_id === projectId);
      const replacement = projectId === null && get().currentSession?.session_id === id && !remaining.length
        ? await chatApi.createSession()
        : null;
      set((state) => ({
        sessions: [...state.sessions.filter((item) => item.session_id !== id), ...(replacement ? [replacement] : [])],
        sessionVersion: state.sessionVersion + 1,
      }));
      // A replacement request must not undo a later session selection.
      if (get().currentSession?.session_id === id && get().sessionEpoch === epoch) {
        const next = get().sessions.find((item) => item.project_id === projectId);
        if (next) await get().selectSession(next.session_id, projectId);
        else set((state) => conversation(state, null, projectId));
      }
    } catch (error) {
      set({ error: errorText(error) });
    }
  },

  updateSession: async (patch) => {
    const session = get().currentSession;
    if (!session) return;
    const epoch = get().sessionEpoch;
    try {
      const updated = await chatApi.updateSession(session.session_id, patch);
      if (get().currentSession?.session_id !== updated.session_id || get().sessionEpoch !== epoch) return;
      set((state) => ({
        currentSession: updated,
        sessions: state.sessions.map((item) => (item.session_id === updated.session_id ? updated : item)),
        sessionVersion: state.sessionVersion + 1,
      }));
    } catch (error) {
      set({ error: errorText(error) });
    }
  },

  activateLocation: async (projectId, sessionId = null) => {
    if (projectId === null) {
      if (get().currentProjectId === null && get().currentSession) return;
      const ordinary = get().sessions.filter((session) => session.kind === 'ordinary');
      const selected = ordinary.find((session) => session.session_id === get().lastOrdinarySessionId) ?? ordinary[0];
      if (selected) await get().selectSession(selected.session_id, null);
      else {
        set((state) => conversation(state, null, null));
        await get().createSession();
      }
      return;
    }
    if (get().currentProjectId === projectId && (get().currentSession?.session_id ?? null) === sessionId &&
        useProjectsStore.getState().projects.some((project) => project.id === projectId)) return;
    set((state) => conversation(state, null, projectId));
    const epoch = get().sessionEpoch;
    try {
      const project = await useProjectsStore.getState().load(projectId);
      if (get().sessionEpoch !== epoch) return;
      if (sessionId) {
        if (project.kind !== 'workspace') throw new Error('PROJECT_CHAT_UNAVAILABLE: Timeline conversations are not available yet.');
        await get().selectSession(sessionId, projectId);
      }
    } catch (error) {
      if (get().sessionEpoch === epoch) set({ error: errorText(error) });
    }
  },

  forgetProject: (projectId) => set((state) => ({
    sessions: state.sessions.filter((session) => session.project_id !== projectId),
    sessionVersion: state.sessionVersion + 1,
    ...(state.currentProjectId === projectId ? conversation(state, null, null) : {}),
  })),

  setError: (error) => set({ error }),
  });
};
