import { create } from 'zustand';
import { api, ApiError } from '../api/client';
import type { GeneralSettings, Message, Run, RunStep, RuntimeEvent, Session } from '../types';

type Store = {
  sessions: Session[];
  currentSession: Session | null;
  messages: Message[];
  runs: Run[];
  stepsByRunId: Record<string, RunStep[]>;
  settings: GeneralSettings | null;
  composerDraftText: string;
  loading: boolean;
  sending: boolean;
  error: string | null;
  initialize: () => Promise<void>;
  refreshCurrent: () => Promise<void>;
  selectSession: (id: string) => Promise<void>;
  createSession: () => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  updateSession: (patch: Partial<Pick<Session, 'title' | 'context_mode' | 'llm_profile_id'>>) => Promise<void>;
  sendMessage: (content: string, attachments?: Record<string, unknown>[]) => Promise<RuntimeEvent | undefined>;
  deleteMessage: (messageId: string) => Promise<void>;
  retryMessage: (messageId: string) => Promise<void>;
  editMessage: (messageId: string, content: string, rerun?: boolean) => Promise<void>;
  cancelRun: (runId: string) => Promise<void>;
  applyRuntimeEvent: (event: RuntimeEvent) => void;
  setComposerDraftText: (text: string) => void;
  setError: (error: string | null) => void;
};

function errorText(error: unknown): string {
  if (error instanceof ApiError) return `${error.code}: ${error.message}`;
  return error instanceof Error ? error.message : String(error || 'Request failed');
}

function mergeMessages(existing: Message[], incoming: Message[]): Message[] {
  const byId = new Map(existing.map((item) => [item.message_id, item]));
  for (const item of incoming) byId.set(item.message_id, item);
  return [...byId.values()].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
}

function mergeRuns(existing: Run[], incoming: Run[]): Run[] {
  const byId = new Map(existing.map((item) => [item.run_id, item]));
  for (const item of incoming) byId.set(item.run_id, item);
  return [...byId.values()].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
}

function stepsFromRuns(runs: Run[]): Record<string, RunStep[]> {
  return Object.fromEntries(runs.map((run) => [run.run_id, run.steps || []]));
}

export const useWorkbenchStore = create<Store>((set, get) => ({
  sessions: [],
  currentSession: null,
  messages: [],
  runs: [],
  stepsByRunId: {},
  settings: null,
  composerDraftText: '',
  loading: false,
  sending: false,
  error: null,

  initialize: async () => {
    set({ loading: true, error: null });
    try {
      let sessions = await api.listSessions();
      if (sessions.length === 0) sessions = [await api.createSession()];
      const selected = sessions[0];
      set({ sessions, currentSession: selected });
      const [settings] = await Promise.all([api.getGeneralSettings(), get().refreshCurrent()]);
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
    try {
      const [freshSession, messages, runs] = await Promise.all([
        api.getSession(session.session_id),
        api.listMessages(session.session_id),
        api.listRuns(session.session_id),
      ]);
      set((state) => ({
        currentSession: freshSession,
        sessions: state.sessions.map((item) => item.session_id === freshSession.session_id ? freshSession : item),
        messages,
        runs,
        stepsByRunId: stepsFromRuns(runs),
      }));
    } catch (error) {
      set({ error: errorText(error) });
    }
  },

  selectSession: async (id) => {
    const session = get().sessions.find((item) => item.session_id === id);
    if (!session) return;
    set({ currentSession: session, messages: [], runs: [], stepsByRunId: {}, error: null });
    await get().refreshCurrent();
  },

  createSession: async () => {
    try {
      const session = await api.createSession();
      set((state) => ({ sessions: [session, ...state.sessions], currentSession: session, messages: [], runs: [], stepsByRunId: {} }));
    } catch (error) {
      set({ error: errorText(error) });
    }
  },

  deleteSession: async (id) => {
    try {
      await api.deleteSession(id);
      const remaining = get().sessions.filter((item) => item.session_id !== id);
      const next = remaining[0] || await api.createSession();
      set({ sessions: remaining.length ? remaining : [next], currentSession: next, messages: [], runs: [], stepsByRunId: {} });
      await get().refreshCurrent();
    } catch (error) {
      set({ error: errorText(error) });
    }
  },

  updateSession: async (patch) => {
    const session = get().currentSession;
    if (!session) return;
    try {
      const updated = await api.updateSession(session.session_id, patch);
      set((state) => ({ currentSession: updated, sessions: state.sessions.map((item) => item.session_id === updated.session_id ? updated : item) }));
    } catch (error) {
      set({ error: errorText(error) });
    }
  },

  sendMessage: async (content, attachments = []) => {
    const session = get().currentSession;
    if (!session || (!content.trim() && attachments.length === 0)) return undefined;
    set({ sending: true, error: null });
    try {
      const response = await api.sendMessage(session.session_id, content, attachments, crypto.randomUUID());
      if (response.messages?.length) set((state) => ({ messages: mergeMessages(state.messages, response.messages || []) }));
      if (response.session) set((state) => ({ currentSession: response.session || null, sessions: state.sessions.map((item) => item.session_id === response.session?.session_id ? response.session as Session : item) }));
      if (response.run) set((state) => ({ runs: mergeRuns(state.runs, [response.run as Run]), stepsByRunId: { ...state.stepsByRunId, [response.run!.run_id]: response.run!.steps || [] } }));
      if (!response.success && response.error) set({ error: `${response.error_code || 'CHAT_FAILED'}: ${response.error}` });
      return response.run ? { type: 'run_completed', session_id: session.session_id, run_id: response.run.run_id } : undefined;
    } catch (error) {
      set({ error: errorText(error) });
    } finally {
      set({ sending: false });
    }
    return undefined;
  },

  deleteMessage: async (messageId) => {
    try {
      await api.deleteMessage(messageId);
      set((state) => ({ messages: state.messages.filter((item) => item.message_id !== messageId) }));
    } catch (error) { set({ error: errorText(error) }); }
  },

  retryMessage: async (messageId) => {
    try {
      const response = await api.retryMessage(messageId);
      if (response.messages?.length) set((state) => ({ messages: mergeMessages(state.messages, response.messages || []) }));
      await get().refreshCurrent();
    } catch (error) { set({ error: errorText(error) }); }
  },

  editMessage: async (messageId, content, rerun = true) => {
    try {
      const response = await api.editMessage(messageId, content, rerun);
      if (response.messages?.length) set((state) => ({ messages: mergeMessages(state.messages, response.messages || []) }));
      await get().refreshCurrent();
    } catch (error) { set({ error: errorText(error) }); }
  },

  cancelRun: async (runId) => {
    try {
      const response = await api.cancelRun(runId);
      set((state) => ({ runs: mergeRuns(state.runs, [response.run]), stepsByRunId: { ...state.stepsByRunId, [runId]: response.run.steps || state.stepsByRunId[runId] || [] } }));
      await get().refreshCurrent();
    } catch (error) { set({ error: errorText(error) }); }
  },

  applyRuntimeEvent: (event) => {
    if (event.session_id !== get().currentSession?.session_id) return;
    const payload = event.payload || {};
    if (event.type === 'message_delta') return;
    if (event.type === 'run_step_updated' || event.type === 'run_step_created') {
      const step = payload.step as RunStep | undefined;
      if (!step) return;
      set((state) => ({ stepsByRunId: { ...state.stepsByRunId, [step.run_id]: [...(state.stepsByRunId[step.run_id] || []).filter((item) => item.step_id !== step.step_id), step].sort((a, b) => a.order - b.order) } }));
    }
    void get().refreshCurrent();
  },

  setComposerDraftText: (text) => set({ composerDraftText: text }),
  setError: (error) => set({ error }),
}));

export default useWorkbenchStore;
