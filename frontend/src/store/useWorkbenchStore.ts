import { create } from 'zustand';
import { applyMessageEvent } from './messageStream';
import { useModelsStore } from './useModelsStore';
import { api, ApiError } from '../api/client';
import type { GeneralSettings, Message, Run, RunStep, RuntimeEvent, Session, SessionPatch, ToolRunResponse } from '../types';

type Store = {
  sessions: Session[];
  currentSession: Session | null;
  messages: Message[];
  runs: Run[];
  stepsByRunId: Record<string, RunStep[]>;
  settings: GeneralSettings | null;
  messageVersion: number;
  sessionVersion: number;
  sourceMessageId: string | null;
  composerDraftText: string;
  loading: boolean;
  sending: boolean;
  resolvingApprovals: string[];
  error: string | null;
  initialize: () => Promise<void>;
  refreshCurrent: () => Promise<void>;
  reloadSessions: () => Promise<void>;
  selectSession: (id: string) => Promise<void>;
  createSession: () => Promise<void>;
  deleteSession: (id: string) => Promise<void>;
  updateSession: (patch: SessionPatch) => Promise<void>;
  sendMessage: (content: string, attachments?: Record<string, unknown>[]) => Promise<RuntimeEvent | undefined>;
  deleteMessage: (messageId: string) => Promise<void>;
  retryMessage: (messageId: string) => Promise<void>;
  editMessage: (messageId: string, content: string, rerun?: boolean) => Promise<void>;
  cancelRun: (runId: string) => Promise<void>;
  resolveApproval: (runId: string, decision: 'approve' | 'reject') => Promise<void>;
  callTool: (name: string, args: Record<string, unknown>) => Promise<ToolRunResponse | undefined>;
  applyRuntimeEvent: (event: RuntimeEvent) => void;
  setComposerDraftText: (text: string) => void;
  setSourceMessageId: (id: string | null) => void;
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
  for (const item of incoming) {
    const previous = byId.get(item.run_id);
    if (previous && (older(item.updated_at, previous.updated_at) || (terminal(previous.status) && !terminal(item.status)))) continue;
    byId.set(item.run_id, { ...item, steps: item.steps || previous?.steps });
  }
  return [...byId.values()].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
}

function terminal(status: Run['status']): boolean { return ['DONE', 'FAILED', 'CANCELLED', 'INTERRUPTED'].includes(status); }

function older(incoming: string, current: string): boolean {
  const delta = Date.parse(incoming) - Date.parse(current);
  if (delta !== 0) return delta < 0;
  // Server timestamps have microseconds; Date.parse alone loses their order.
  const fraction = (value: string) => (value.match(/\.(\d+)/)?.[1] || '').padEnd(9, '0');
  return fraction(incoming) < fraction(current);
}

function mergeSteps(existing: Record<string, RunStep[]>, steps: RunStep[]): Record<string, RunStep[]> {
  const result = { ...existing };
  for (const step of steps) {
    const rows = result[step.run_id] || [];
    const previous = rows.find((item) => item.step_id === step.step_id);
    if (previous && (older(step.updated_at, previous.updated_at) ||
        (['completed', 'failed', 'skipped'].includes(previous.status) && ['pending', 'running'].includes(step.status)))) continue;
    result[step.run_id] = [...rows.filter((item) => item.step_id !== step.step_id), step].sort((a, b) => a.order - b.order);
  }
  return result;
}

function toolResponseState(state: Store, response: ToolRunResponse): Partial<Store> {
  if (state.currentSession?.session_id !== response.run.session_id) return {};
  const previous = state.runs.find((run) => run.run_id === response.run.run_id);
  const acceptSession = !previous || !older(response.run.updated_at, previous.updated_at);
  return {
    runs: mergeRuns(state.runs, [response.run]),
    stepsByRunId: mergeSteps(state.stepsByRunId, response.run.steps || []),
    messages: mergeMessages(state.messages, response.messages.filter((m) => m.session_id === response.run.session_id)),
    currentSession: acceptSession && !older(response.session.updated_at, state.currentSession.updated_at) ? response.session : state.currentSession,
    sessions: acceptSession ? state.sessions.map((s) => s.session_id === response.session.session_id && !older(response.session.updated_at, s.updated_at) ? response.session : s) : state.sessions,
    messageVersion: state.messageVersion + 1,
    sessionVersion: state.sessionVersion + 1,
  };
}

export const useWorkbenchStore = create<Store>((set, get) => ({
  sessions: [],
  currentSession: null,
  messages: [],
  runs: [],
  stepsByRunId: {},
  settings: null,
  messageVersion: 0,
  sessionVersion: 0,
  sourceMessageId: null,
  composerDraftText: '',
  loading: false,
  sending: false,
  resolvingApprovals: [],
  error: null,

  initialize: async () => {
    set({ loading: true, error: null });
    try {
      let sessions = await api.listSessions();
      if (sessions.length === 0) sessions = [await api.createSession()];
      const selected = sessions[0];
      set({ sessions, currentSession: selected });
      const [settings] = await Promise.all([api.getGeneralSettings(), get().refreshCurrent(), useModelsStore.getState().reload()]);
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
        api.getSession(session.session_id),
        api.listMessages(session.session_id),
        api.listRuns(session.session_id),
      ]);
      if (get().currentSession?.session_id !== session.session_id) return;
      set((state) => ({
        currentSession: state.sessionVersion === sessionVersion ? freshSession : state.currentSession,
        sessions: state.sessionVersion === sessionVersion ? state.sessions.map((item) => item.session_id === freshSession.session_id ? freshSession : item) : state.sessions,
        messages: state.messageVersion !== version ? mergeMessages(messages, state.messages) : mergeMessages(state.messages.filter((m) => m.metadata?.streaming && runs.some((r) => r.run_id === m.run_id && r.status === "RUNNING")), messages),
        runs: mergeRuns(state.runs, runs),
        stepsByRunId: mergeSteps(state.stepsByRunId, runs.flatMap((run) => run.steps || [])),
      }));
    } catch (error) {
      set({ error: errorText(error) });
    }
  },

  reloadSessions: async () => {
    const version = get().sessionVersion;
    const sessions = await api.listSessions();
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
      const session = await api.createSession();
      set((state) => ({ sessions: [session, ...state.sessions], currentSession: session, messages: [], runs: [], stepsByRunId: {}, sourceMessageId: null }));
    } catch (error) {
      set({ error: errorText(error) });
    }
  },

  deleteSession: async (id) => {
    try {
      await api.deleteSession(id);
      const remaining = get().sessions.filter((item) => item.session_id !== id);
      const next = remaining[0] || await api.createSession();
      set({ sessions: remaining.length ? remaining : [next], currentSession: next, messages: [], runs: [], stepsByRunId: {}, sourceMessageId: null });
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
      if (get().currentSession?.session_id !== updated.session_id) return;
      set((state) => ({ currentSession: updated, sessions: state.sessions.map((item) => item.session_id === updated.session_id ? updated : item), sessionVersion: state.sessionVersion + 1 }));
    } catch (error) {
      set({ error: errorText(error) });
    }
  },

  sendMessage: async (content, attachments = []) => {
    const session = get().currentSession;
    if (!session || (!content.trim() && attachments.length === 0)) return undefined;
    set({ sending: true, error: null });
    try {
      const response = await api.sendMessage(session.session_id, content, attachments, crypto.randomUUID(), get().sourceMessageId);
      if (response.run && response.session) set((state) => toolResponseState(state, { run: response.run!, session: response.session!, messages: response.messages || [] }));
      if (!response.success && response.error && get().currentSession?.session_id === session.session_id) set({ error: `${response.error_code || 'CHAT_FAILED'}: ${response.error}` });
      return response.success && response.run ? { type: response.run.status === 'WAITING_FOR_USER' ? 'approval_requested' : 'run_completed', session_id: session.session_id, run_id: response.run.run_id } : undefined;
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
      set((state) => ({ messages: state.messages.filter((item) => item.message_id !== messageId), sourceMessageId: state.sourceMessageId === messageId ? null : state.sourceMessageId }));
    } catch (error) { set({ error: errorText(error) }); }
  },

  retryMessage: async (messageId) => {
    try {
      const response = await api.retryMessage(messageId);
      if (response.messages?.length && response.session?.session_id === get().currentSession?.session_id) set((state) => ({ messages: mergeMessages(state.messages, response.messages || []) }));
      await get().refreshCurrent();
    } catch (error) { set({ error: errorText(error) }); }
  },

  editMessage: async (messageId, content, rerun = true) => {
    try {
      const response = await api.editMessage(messageId, content, rerun);
      if (response.messages?.length && response.session?.session_id === get().currentSession?.session_id) set((state) => ({ messages: mergeMessages(state.messages, response.messages || []) }));
      await get().refreshCurrent();
    } catch (error) { set({ error: errorText(error) }); }
  },

  cancelRun: async (runId) => {
    const sessionId = get().currentSession?.session_id;
    try {
      const response = await api.cancelRun(runId);
      if (get().currentSession?.session_id !== response.run.session_id) return;
      set((state) => ({ runs: mergeRuns(state.runs, [response.run]), stepsByRunId: mergeSteps(state.stepsByRunId, response.run.steps || []) }));
      await get().refreshCurrent();
    } catch (error) { if (get().currentSession?.session_id === sessionId) set({ error: errorText(error) }); }
  },

  resolveApproval: async (runId, decision) => {
    if (get().resolvingApprovals.includes(runId)) return;
    const sessionId = get().currentSession?.session_id;
    set((state) => ({ resolvingApprovals: [...state.resolvingApprovals, runId], error: null }));
    try {
      const response = await api.resolveToolApproval(runId, decision);
      set((state) => toolResponseState(state, response));
    } catch (error) { if (get().currentSession?.session_id === sessionId) set({ error: errorText(error) }); }
    finally { set((state) => ({ resolvingApprovals: state.resolvingApprovals.filter((id) => id !== runId) })); }
  },

  callTool: async (name, args) => {
    const session = get().currentSession;
    if (!session || get().sending) return undefined;
    set({ sending: true, error: null });
    try {
      const response = await api.callTool(name, session.session_id, args);
      set((state) => toolResponseState(state, response));
      return response;
    } catch (error) { if (get().currentSession?.session_id === session.session_id) set({ error: errorText(error) }); }
    finally { set({ sending: false }); }
    return undefined;
  },

  applyRuntimeEvent: (event) => {
    if (event.type === 'session_updated' && event.payload?.session) {
      const session = event.payload.session as Session;
      set((state) => ({
        currentSession: state.currentSession?.session_id === session.session_id ? session : state.currentSession,
        sessions: state.sessions.map((s) => s.session_id === session.session_id ? session : s),
        sessionVersion: state.sessionVersion + 1,
      }));
      return;
    }
    if (event.type === 'model_status' && event.payload?.model_profile_id) {
      return;
    }
    if (event.session_id !== get().currentSession?.session_id) return;
    const payload = event.payload || {};
    if (['message_started', 'message_delta', 'message_completed', 'tool_call_created', 'tool_result_created'].includes(event.type)) {
      if (event.type === 'message_started' && get().runs.some((r) => r.run_id === event.run_id && ['DONE', 'FAILED', 'CANCELLED', 'INTERRUPTED'].includes(r.status))) return;
      set((state) => ({ messages: applyMessageEvent(state.messages, event), messageVersion: state.messageVersion + 1 }));
      return;
    }
    if (['run_failed', 'run_cancelled'].includes(event.type)) {
      set((state) => ({ messages: state.messages.filter((m) => m.run_id !== event.run_id || !m.metadata?.streaming), messageVersion: state.messageVersion + 1 }));
    }
    if (payload.run) {
      const incoming = payload.run as Run;
      if (incoming.session_id !== event.session_id) return;
      set((state) => {
        const previous = state.runs.find((run) => run.run_id === incoming.run_id);
        if (previous && (older(incoming.updated_at, previous.updated_at) || (terminal(previous.status) && !terminal(incoming.status)))) return {};
        const session = state.currentSession;
        const currentSession = session ? { ...session, waiting_run_id: incoming.status === 'WAITING_FOR_USER' ? incoming.run_id : session.waiting_run_id === incoming.run_id ? null : session.waiting_run_id } : null;
        return { runs: mergeRuns(state.runs, [incoming]), currentSession, sessionVersion: state.sessionVersion + 1,
          sessions: currentSession ? state.sessions.map((s) => s.session_id === currentSession.session_id ? currentSession : s) : state.sessions };
      });
    }
    if (event.type === 'run_step_updated' || event.type === 'run_step_created') {
      const step = payload.step as RunStep | undefined;
      if (!step) return;
      set((state) => ({ stepsByRunId: mergeSteps(state.stepsByRunId, [step]) }));
    }
    if (['run_started', 'run_completed', 'run_failed', 'run_cancelled'].includes(event.type)) void get().refreshCurrent();
  },

  setComposerDraftText: (text) => set({ composerDraftText: text }),
  setSourceMessageId: (sourceMessageId) => set({ sourceMessageId }),
  setError: (error) => set({ error }),
}));

export default useWorkbenchStore;
