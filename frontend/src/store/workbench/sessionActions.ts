import type { WorkbenchActions } from './state';
import { errorText, mergeMessages, mergeRuns, mergeSteps } from './mergeState';

import { useModelsStore } from '../useModelsStore';
import { chatApi } from '../../api/chat';
import { settingsApi } from '../../api/settings';
import { runsApi } from '../../api/runs';

export const createSessionActions: WorkbenchActions<
  | 'initialize'
  | 'refreshCurrent'
  | 'reloadSessions'
  | 'selectSession'
  | 'createSession'
  | 'deleteSession'
  | 'updateSession'
  | 'setError'
> = (set, get) => ({
  initialize: async () => {
    set({ loading: true, error: null });
    try {
      let sessions = await chatApi.listSessions();
      if (sessions.length === 0) sessions = [await chatApi.createSession()];
      const selected = sessions[0];
      set({ sessions, currentSession: selected });
      const [settings] = await Promise.all([
        settingsApi.getGeneralSettings(),
        get().refreshCurrent(),
        useModelsStore.getState().reload(),
      ]);
      set({ settings });
    } catch (error) {
      set({ error: errorText(error) });
    } finally {
      set({ loading: false });
    }
  },

  refreshCurrent: async () => {
    const session = get().currentSession;
    if (!session) return;
    const version = get().messageVersion;
    const sessionVersion = get().sessionVersion;
    try {
      const [freshSession, messages, runs] = await Promise.all([
        chatApi.getSession(session.session_id),
        chatApi.listMessages(session.session_id),
        runsApi.listRuns(session.session_id),
      ]);
      if (get().currentSession?.session_id !== session.session_id) return;
      set((state) => ({
        currentSession: state.sessionVersion === sessionVersion ? freshSession : state.currentSession,
        sessions:
          state.sessionVersion === sessionVersion
            ? state.sessions.map((item) => (item.session_id === freshSession.session_id ? freshSession : item))
            : state.sessions,
        messages:
          state.messageVersion !== version
            ? mergeMessages(messages, state.messages)
            : mergeMessages(
                state.messages.filter(
                  (m) => m.metadata?.streaming && runs.some((r) => r.run_id === m.run_id && r.status === 'RUNNING'),
                ),
                messages,
              ),
        runs: mergeRuns(state.runs, runs),
        stepsByRunId: mergeSteps(
          state.stepsByRunId,
          runs.flatMap((run) => run.steps || []),
        ),
      }));
    } catch (error) {
      set({ error: errorText(error) });
    }
  },

  reloadSessions: async () => {
    const version = get().sessionVersion;
    const sessions = await chatApi.listSessions();
    if (version === get().sessionVersion) set({ sessions });
    await get().refreshCurrent();
  },

  selectSession: async (id) => {
    const session = get().sessions.find((item) => item.session_id === id);
    if (!session) return;
    set({ currentSession: session, messages: [], runs: [], stepsByRunId: {}, error: null, sourceMessageId: null });
    await get().refreshCurrent();
  },

  createSession: async () => {
    try {
      const session = await chatApi.createSession();
      set((state) => ({
        sessions: [session, ...state.sessions],
        currentSession: session,
        messages: [],
        runs: [],
        stepsByRunId: {},
        sourceMessageId: null,
      }));
    } catch (error) {
      set({ error: errorText(error) });
    }
  },

  deleteSession: async (id) => {
    try {
      await chatApi.deleteSession(id);
      const remaining = get().sessions.filter((item) => item.session_id !== id);
      const next = remaining[0] || (await chatApi.createSession());
      set({
        sessions: remaining.length ? remaining : [next],
        currentSession: next,
        messages: [],
        runs: [],
        stepsByRunId: {},
        sourceMessageId: null,
      });
      await get().refreshCurrent();
    } catch (error) {
      set({ error: errorText(error) });
    }
  },

  updateSession: async (patch) => {
    const session = get().currentSession;
    if (!session) return;
    try {
      const updated = await chatApi.updateSession(session.session_id, patch);
      if (get().currentSession?.session_id !== updated.session_id) return;
      set((state) => ({
        currentSession: updated,
        sessions: state.sessions.map((item) => (item.session_id === updated.session_id ? updated : item)),
        sessionVersion: state.sessionVersion + 1,
      }));
    } catch (error) {
      set({ error: errorText(error) });
    }
  },

  setError: (error) => set({ error }),
});
