import { create } from 'zustand';
import { ApiError, api } from '../api/client';
import { parseServerTime } from '../utils/time';
import type {
  Agent,
  AgentConfig,
  AppError,
  AvailableAction,
  CapabilityConfig,
  Command,
  LlmResolvedConfig,
  LlmProfile,
  LlmTestResult,
  Message,
  Run,
  RunEvent,
  HealthDetails,
  RuntimeEvent,
  Session,
  SendMessageAttachment,
} from '../types';

type WorkbenchState = {
  agents: Agent[];
  commands: Command[];
  agentConfigs: AgentConfig[];
  capabilityConfigs: CapabilityConfig[];
  llmProfiles: LlmProfile[];
  sessions: Session[];
  currentSession?: Session;
  messages: Message[];
  runs: Run[];
  runEvents: Record<string, RunEvent[]>;
  health?: HealthDetails;
  runEventLoading?: string;
  loading: boolean;
  creatingSession: boolean;
  sending: boolean;
  activeRunId?: string;
  savingConfigId?: string;
  testingLlm: boolean;
  pendingActionKey?: string;
  pendingMessageActionId?: string;
  error?: string;
  lastError?: AppError;
  setError: (error: unknown, fallback: string) => void;
  clearError: () => void;
  initialize: () => Promise<void>;
  refreshCurrent: () => Promise<void>;
  createSession: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  deleteSession: (sessionId: string) => Promise<void>;
  renameSession: (sessionId: string, title: string) => Promise<void>;
  updateDefaultAgent: (agentId: string) => Promise<void>;
  updateSessionLlmProfile: (profileId: string | null) => Promise<void>;
  refreshConfigs: () => Promise<void>;
  updateAgentConfig: (agentId: string, patch: Partial<Pick<AgentConfig, 'enabled' | 'user_config'>>) => Promise<void>;
  updateCapabilityConfig: (
    capabilityId: string,
    patch: Partial<Pick<CapabilityConfig, 'enabled' | 'user_config'>>,
  ) => Promise<void>;
  getResolvedLlmConfig: () => Promise<LlmResolvedConfig | null>;
  testLlmConnection: () => Promise<LlmTestResult>;
  refreshHealth: () => Promise<void>;
  loadRunEvents: (runId: string) => Promise<void>;
  applyRuntimeEvent: (event: RuntimeEvent) => void;
  sendMessage: (content: string, attachments?: SendMessageAttachment[]) => Promise<boolean>;
  cancelActiveRun: () => Promise<void>;
  invokeAction: (action: AvailableAction) => Promise<void>;
  deleteMessage: (messageId: string) => Promise<void>;
  retryMessage: (messageId: string) => Promise<void>;
  editMessage: (messageId: string, content: string) => Promise<void>;
};

export const actionKey = (action: AvailableAction) => `${action.source_message_id}-${action.agent_id}-${action.action_id}`;

export const useWorkbenchStore = create<WorkbenchState>((set, get) => ({
  agents: [],
  commands: [],
  agentConfigs: [],
  capabilityConfigs: [],
  llmProfiles: [],
  sessions: [],
  messages: [],
  runs: [],
  runEvents: {},
  loading: false,
  creatingSession: false,
  sending: false,
  testingLlm: false,

  setError: (error, fallback) => set(formatError(error, fallback)),
  clearError: () => set({ error: undefined, lastError: undefined }),

  initialize: async () => {
    set({ loading: true, error: undefined, lastError: undefined });
    try {
      const [agents, commands, sessions, agentConfigs, capabilityConfigs, llmProfiles] = await Promise.all([
        api.listAgents(),
        api.listCommands(),
        api.listSessions(),
        api.listAgentConfigs(),
        api.listCapabilityConfigs(),
        api.listLlmProfiles(),
      ]);
      const sortedSessions = sortSessionsByRecent(sessions);
      const currentSession = sortedSessions[0];
      set({ agents, commands, sessions: sortedSessions, currentSession, agentConfigs, capabilityConfigs, llmProfiles, loading: false });
      if (currentSession) {
        await get().refreshCurrent();
      }
      await get().refreshHealth();
    } catch (error) {
      set({ ...formatError(error, 'Failed to initialize'), loading: false });
    }
  },

  refreshCurrent: async () => {
    const session = get().currentSession;
    if (!session) return;
    const [freshSession, messages, runs] = await Promise.all([
      api.getSession(session.session_id),
      api.listMessages(session.session_id),
      api.listRuns(session.session_id),
    ]);
    if (get().currentSession?.session_id !== session.session_id) return;
    const sessions = await api.listSessions();
    if (get().currentSession?.session_id !== session.session_id) return;
    set({
      currentSession: freshSession,
      sessions: sortSessionsByRecent(sessions),
      messages: buildTimeline(messages, runs, get().messages, session.session_id),
      runs,
    });
  },

  createSession: async () => {
    if (get().creatingSession) return;
    const defaultAgentId = chooseEnabledDefaultAgent(get().agents, get().currentSession?.default_agent_id);
    if (!defaultAgentId) {
      set({
        error: 'NO_ENABLED_AGENT: Enable at least one agent before creating a session.',
        lastError: { code: 'NO_ENABLED_AGENT', message: 'Enable at least one agent before creating a session.' },
      });
      return;
    }

    set({ creatingSession: true, error: undefined, lastError: undefined });
    try {
      const session = await api.createSession(`Session ${get().sessions.length + 1}`, defaultAgentId);
      const sessions = sortSessionsByRecent(await api.listSessions());
      set({ sessions, currentSession: session, messages: [], runs: [], creatingSession: false });
    } catch (error) {
      set({ ...formatError(error, 'Failed to create session'), creatingSession: false });
    }
  },

  selectSession: async (sessionId: string) => {
    const session = await api.getSession(sessionId);
    set({ currentSession: session });
    await get().refreshCurrent();
  },

  deleteSession: async (sessionId: string) => {
    const existingSessions = get().sessions;
    const deletingCurrent = get().currentSession?.session_id === sessionId;
    const nextSession = deletingCurrent ? existingSessions.find((session) => session.session_id !== sessionId) : undefined;

    try {
      await api.deleteSession(sessionId);
      if (deletingCurrent) {
        set({ currentSession: nextSession, messages: [], runs: [], runEvents: {} });
      }
      const sessions = sortSessionsByRecent((await api.listSessions()).filter((session) => session.session_id !== sessionId));
      if (!deletingCurrent) {
        set({
          sessions,
          error: undefined,
          lastError: undefined,
        });
        return;
      }

      if (!nextSession) {
        set({
          sessions,
          currentSession: undefined,
          messages: [],
          runs: [],
          runEvents: {},
          error: undefined,
          lastError: undefined,
        });
        return;
      }

      const freshNextSession = sessions.find((session) => session.session_id === nextSession.session_id) || nextSession;
      set({
        sessions,
        currentSession: freshNextSession,
        messages: [],
        runs: [],
        runEvents: {},
        error: undefined,
        lastError: undefined,
      });
      await get().refreshCurrent();
    } catch (error) {
      set(formatError(error, 'Failed to delete session'));
    }
  },

  renameSession: async (sessionId: string, title: string) => {
    const trimmed = title.trim();
    if (!trimmed) {
      const emptyTitle = { code: 'SESSION_TITLE_EMPTY', message: 'Session title cannot be empty.' };
      set({ error: `${emptyTitle.code}: ${emptyTitle.message}`, lastError: emptyTitle });
      throw new Error(emptyTitle.message);
    }
    try {
      const updated = await api.updateSession(sessionId, { title: trimmed });
      set({
        currentSession: get().currentSession?.session_id === updated.session_id ? updated : get().currentSession,
        sessions: sortSessionsByRecent(get().sessions.map((item) => (item.session_id === updated.session_id ? updated : item))),
        error: undefined,
        lastError: undefined,
      });
    } catch (error) {
      set(formatError(error, 'Failed to rename session'));
      throw error;
    }
  },

  updateDefaultAgent: async (agentId: string) => {
    const session = get().currentSession;
    if (!session) return;
    const agent = get().agents.find((item) => item.id === agentId);
    if (!agent?.enabled) {
      set({
        error: 'AGENT_DISABLED: Cannot select a disabled agent.',
        lastError: { code: 'AGENT_DISABLED', message: 'Cannot select a disabled agent.' },
      });
      return;
    }
    try {
      const updated = await api.updateSession(session.session_id, { default_agent_id: agentId });
      set({
        currentSession: updated,
        sessions: sortSessionsByRecent(get().sessions.map((item) => (item.session_id === updated.session_id ? updated : item))),
        error: undefined,
        lastError: undefined,
      });
    } catch (error) {
      set(formatError(error, 'Failed to update default agent'));
    }
  },

  updateSessionLlmProfile: async (profileId: string | null) => {
    const session = get().currentSession;
    if (!session) return;
    if (profileId) {
      const profile = get().llmProfiles.find((item) => item.id === profileId);
      if (!profile || !profile.enabled) {
        set({
          error: 'LLM_PROFILE_NOT_FOUND: Select an enabled saved profile.',
          lastError: { code: 'LLM_PROFILE_NOT_FOUND', message: 'Select an enabled saved profile.' },
        });
        return;
      }
    }
    try {
      const updated = await api.updateSession(session.session_id, { llm_profile_id: profileId });
      set({
        currentSession: updated,
        sessions: sortSessionsByRecent(get().sessions.map((item) => (item.session_id === updated.session_id ? updated : item))),
        error: undefined,
        lastError: undefined,
      });
    } catch (error) {
      set(formatError(error, 'Failed to update session model'));
    }
  },

  refreshConfigs: async () => {
    const [agents, commands, agentConfigs, capabilityConfigs, llmProfiles] = await Promise.all([
      api.listAgents(),
      api.listCommands(),
      api.listAgentConfigs(),
      api.listCapabilityConfigs(),
      api.listLlmProfiles(),
    ]);
    set({ agents, commands, agentConfigs, capabilityConfigs, llmProfiles });
  },

  updateAgentConfig: async (agentId, patch) => {
    set({ savingConfigId: `agent:${agentId}`, error: undefined, lastError: undefined });
    try {
      await api.updateAgentConfig(agentId, patch);
      await get().refreshConfigs();
      set({ savingConfigId: undefined });
    } catch (error) {
      set({ ...formatError(error, 'Failed to update agent config'), savingConfigId: undefined });
      throw error;
    }
  },

  updateCapabilityConfig: async (capabilityId, patch) => {
    set({ savingConfigId: `capability:${capabilityId}`, error: undefined, lastError: undefined });
    try {
      await api.updateCapabilityConfig(capabilityId, patch);
      await get().refreshConfigs();
      set({ savingConfigId: undefined });
    } catch (error) {
      set({ ...formatError(error, 'Failed to update capability config'), savingConfigId: undefined });
      throw error;
    }
  },

  getResolvedLlmConfig: async () => {
    try {
      return await api.getResolvedLlmConfig();
    } catch (error) {
      set(formatError(error, 'Failed to load LLM config status'));
      return null;
    }
  },

  testLlmConnection: async () => {
    set({ testingLlm: true, error: undefined, lastError: undefined });
    try {
      const result = await api.testLlmConnection();
      if (!result.success) {
        set({
          lastError: { code: result.error_code || 'LLM_CONNECTION_FAILED', message: result.message },
          error: `${result.error_code || 'LLM_CONNECTION_FAILED'}: ${result.message}`,
        });
      }
      set({ testingLlm: false });
      return result;
    } catch (error) {
      const formatted = formatError(error, 'LLM test failed');
      set({ ...formatted, testingLlm: false });
      return { success: false, message: formatted.lastError.message, base_url: '', error_code: formatted.lastError.code };
    }
  },

  refreshHealth: async () => {
    try {
      const health = await api.getHealthDetails();
      set({ health });
    } catch (error) {
      set(formatError(error, 'Failed to load backend health'));
    }
  },

  loadRunEvents: async (runId: string) => {
    set({ runEventLoading: runId, error: undefined, lastError: undefined });
    try {
      const events = await api.listRunEvents(runId);
      set({ runEvents: { ...get().runEvents, [runId]: events }, runEventLoading: undefined });
    } catch (error) {
      set({ ...formatError(error, 'Failed to load run timeline'), runEventLoading: undefined });
    }
  },

  sendMessage: async (content: string, attachments: SendMessageAttachment[] = []) => {
    const session = get().currentSession;
    if (!session || (!content.trim() && !attachments.length) || get().sending) return false;
    const optimisticMessage = createOptimisticUserMessage(session, content, attachments);
    set({
      messages: [...get().messages, optimisticMessage],
      sending: true,
      error: undefined,
      lastError: undefined,
    });
    try {
      const result = await api.sendMessage(session.session_id, content, attachments);
      await get().refreshCurrent();
      if (!result.success) {
        set({ error: undefined, lastError: undefined });
      }
      set({ sending: false, activeRunId: undefined });
      return true;
    } catch (error) {
      const formatted = formatError(error, 'Message failed');
      set({
        error: undefined,
        lastError: undefined,
        sending: false,
        messages: get().messages.map((message) =>
          message.message_id === optimisticMessage.message_id
            ? { ...message, client_status: 'failed', client_error: formatted.lastError }
            : message,
        ),
      });
      return false;
    }
  },

  applyRuntimeEvent: (event: RuntimeEvent) => {
    const session = get().currentSession;
    if (!session || event.session_id !== session.session_id) return;
    if (event.type === 'run_started' && event.run_id) {
      set({ activeRunId: event.run_id, sending: true });
      return;
    }
    if (event.type === 'message_started' && event.run_id) {
      const draft = createDraftAssistantMessage(session.session_id, event);
      set({
        activeRunId: event.run_id,
        sending: true,
        messages: upsertDraftMessage(get().messages, draft),
      });
      return;
    }
    if (event.type === 'message_delta' && event.run_id) {
      const delta = typeof event.payload.delta === 'string' ? event.payload.delta : '';
      const reasoningDelta = typeof event.payload.reasoning_delta === 'string' ? event.payload.reasoning_delta : '';
      if (!delta && !reasoningDelta) return;
      set({ messages: appendDraftDelta(get().messages, event, delta, reasoningDelta) });
      return;
    }
    if (event.type === 'message_completed') {
      const finalMessage = parseMessagePayload(event.payload.message);
      if (finalMessage) {
        set({ messages: replaceDraftWithFinal(get().messages, finalMessage, String(event.payload.draft_message_id || '')) });
      }
      return;
    }
    if (event.type === 'run_metrics') {
      set({ messages: attachDraftMetrics(get().messages, event) });
      return;
    }
    if (event.type === 'run_failed') {
      const error = {
        code: 'RUN_FAILED',
        message: typeof event.payload.error === 'string' ? event.payload.error : 'Run failed.',
      };
      set({
        sending: false,
        activeRunId: undefined,
        messages: removeDraftAndAppendError(get().messages, session.session_id, event.run_id || '', error),
      });
      return;
    }
    if (event.type === 'run_cancelled') {
      set({
        sending: false,
        activeRunId: undefined,
        messages: markDraftInterrupted(get().messages, event.run_id || ''),
      });
      return;
    }
    if (event.type === 'run_done') {
      set({ sending: false, activeRunId: undefined });
    }
  },

  cancelActiveRun: async () => {
    const runId = get().activeRunId || runningRunId(get().runs);
    if (!runId) return;
    try {
      await api.cancelRun(runId);
      set({ sending: false, activeRunId: undefined, messages: markDraftInterrupted(get().messages, runId) });
      await get().refreshCurrent();
    } catch (error) {
      set(formatError(error, 'Failed to stop generation'));
    }
  },

  invokeAction: async (action: AvailableAction) => {
    const session = get().currentSession;
    if (!session) return;
    const key = actionKey(action);
    set({ pendingActionKey: key, error: undefined, lastError: undefined });
    try {
      const result = await api.invokeAction(session.session_id, {
        agent_id: action.agent_id,
        action_id: action.action_id,
        source_message_id: action.source_message_id,
        prefill: action.prefill,
      });
      await get().refreshCurrent();
      if (!result.success) {
        set({ error: undefined, lastError: undefined });
      }
      set({ pendingActionKey: undefined });
    } catch (error) {
      const formatted = formatError(error, 'Action failed');
      set({
        error: undefined,
        lastError: undefined,
        pendingActionKey: undefined,
        messages: [...get().messages, createInlineErrorMessage(session.session_id, formatted.lastError, action.source_message_id)],
      });
    }
  },

  deleteMessage: async (messageId: string) => {
    const session = get().currentSession;
    if (!session) return;
    set({ pendingMessageActionId: messageId, error: undefined, lastError: undefined });
    try {
      await api.deleteMessage(messageId);
      set({
        pendingMessageActionId: undefined,
        messages: get().messages.filter((message) => message.message_id !== messageId),
        error: undefined,
        lastError: undefined,
      });
    } catch (error) {
      set({ ...formatError(error, 'Failed to delete message'), pendingMessageActionId: undefined });
    }
  },

  retryMessage: async (messageId: string) => {
    const session = get().currentSession;
    if (!session) return;
    set({ pendingMessageActionId: messageId, error: undefined, lastError: undefined });
    try {
      const result = await api.retryMessage(messageId);
      await get().refreshCurrent();
      if (!result.success) {
        set({ error: undefined, lastError: undefined });
      }
      set({ pendingMessageActionId: undefined });
    } catch (error) {
      set({ ...formatError(error, 'Failed to retry message'), pendingMessageActionId: undefined });
    }
  },

  editMessage: async (messageId: string, content: string) => {
    const session = get().currentSession;
    if (!session) return;
    set({ pendingMessageActionId: messageId, error: undefined, lastError: undefined });
    try {
      const result = await api.editMessage(messageId, content, true);
      await get().refreshCurrent();
      if (!result.success) {
        set({ error: undefined, lastError: undefined });
      }
      set({ pendingMessageActionId: undefined });
    } catch (error) {
      set({ ...formatError(error, 'Failed to edit message'), pendingMessageActionId: undefined });
      throw error;
    }
  },
}));

function createOptimisticUserMessage(session: Session, content: string, attachments: SendMessageAttachment[]): Message {
  return {
    message_id: `optimistic-${newClientId()}`,
    session_id: session.session_id,
    role: 'user',
    content,
    agent_id: null,
    command_name: null,
    action_id: null,
    run_id: null,
    output_type: 'text',
    parent_message_id: null,
    available_actions: [],
    metadata: { attachments },
    created_at: new Date().toISOString(),
    client_status: 'pending',
  };
}

function createInlineErrorMessage(sessionId: string, error: AppError, parentMessageId?: string | null): Message {
  return {
    message_id: `error-${newClientId()}`,
    session_id: sessionId,
    role: 'system',
    content: { code: error.code, message: error.message },
    agent_id: null,
    command_name: null,
    action_id: null,
    run_id: null,
    output_type: 'error',
    parent_message_id: parentMessageId || null,
    available_actions: [],
    created_at: new Date().toISOString(),
    client_status: 'failed',
    client_error: error,
  };
}

function createDraftAssistantMessage(sessionId: string, event: RuntimeEvent): Message {
  const payload = event.payload || {};
  return {
    message_id: typeof event.message_id === 'string' && event.message_id ? event.message_id : `draft-${event.run_id || newClientId()}`,
    session_id: sessionId,
    role: 'assistant',
    content: '',
    agent_id: typeof payload.agent_id === 'string' ? payload.agent_id : null,
    command_name: null,
    action_id: 'default',
    run_id: event.run_id || null,
    output_type: 'text',
    parent_message_id: null,
    available_actions: [],
    metadata: {
      llm_resolution: isRecord(payload.llm_resolution) ? payload.llm_resolution : undefined,
      streaming: true,
    },
    created_at: typeof payload.created_at === 'string' ? payload.created_at : event.created_at,
    client_status: 'streaming',
  };
}

function buildTimeline(fetchedMessages: Message[], runs: Run[], current: Message[], sessionId: string): Message[] {
  const messages = [...fetchedMessages, ...failedRunErrors(fetchedMessages, runs)];
  return mergeTransientMessages(sortMessagesByCreatedAt(messages), current, sessionId);
}

function failedRunErrors(messages: Message[], runs: Run[]): Message[] {
  const messageRunIds = new Set(messages.map((message) => message.run_id).filter(Boolean));
  return runs
    .filter((run) => run.status === 'FAILED' && run.error && !messageRunIds.has(run.run_id))
    .map((run) => {
      const parentMessageId = firstString(run.metadata, ['parent_message_id', 'input_message_id', 'source_message_id']);
      return {
        message_id: `run-error-${run.run_id}`,
        session_id: run.session_id,
        role: 'system',
        content: { code: 'RUN_FAILED', message: run.error || 'Run failed.' },
        agent_id: null,
        command_name: null,
        action_id: run.action_id,
        run_id: run.run_id,
        output_type: 'error',
        parent_message_id: parentMessageId,
        metadata: { synthetic: true, run_kind: run.kind, target_id: run.target_id },
        available_actions: [],
        created_at: run.updated_at || run.created_at,
        client_status: 'failed',
        client_error: { code: 'RUN_FAILED', message: run.error || 'Run failed.' },
      } satisfies Message;
    });
}

function sortMessagesByCreatedAt(messages: Message[]): Message[] {
  return messages
    .map((message, index) => ({ message, index }))
    .sort((left, right) => {
      const leftTime = parseServerTime(left.message.created_at || '').getTime();
      const rightTime = parseServerTime(right.message.created_at || '').getTime();
      const normalizedLeft = Number.isNaN(leftTime) ? 0 : leftTime;
      const normalizedRight = Number.isNaN(rightTime) ? 0 : rightTime;
      if (normalizedLeft !== normalizedRight) return normalizedLeft - normalizedRight;
      return left.index - right.index;
    })
    .map((item) => item.message);
}

function firstString(source: Record<string, unknown> | undefined, keys: string[]): string | null {
  if (!source) return null;
  for (const key of keys) {
    const value = source[key];
    if (typeof value === 'string' && value) return value;
  }
  return null;
}

function mergeTransientMessages(fetched: Message[], current: Message[], sessionId: string): Message[] {
  const transient = current.filter(
    (message) => message.session_id === sessionId && message.client_status && isTransientMessage(message),
  );
  if (!transient.length) return fetched;

  const fetchedRunIds = new Set(fetched.map((message) => message.run_id).filter(Boolean));
  const remaining = transient.filter((message) => {
    if (message.run_id && fetchedRunIds.has(message.run_id)) return false;
    if (message.role === 'user' && message.client_status === 'pending' && hasFetchedReplacementUser(fetched, message)) return false;
    if (message.role !== 'user') return true;
    return !fetched.some((candidate) => candidate.role === 'user' && candidate.content === message.content && sameAttachmentIds(candidate, message));
  });

  return [...fetched, ...remaining];
}

function isTransientMessage(message: Message): boolean {
  return message.message_id.startsWith('optimistic-') || message.message_id.startsWith('error-') || message.message_id.startsWith('draft-');
}

function hasFetchedReplacementUser(fetched: Message[], pending: Message): boolean {
  const pendingTime = parseServerTime(pending.created_at || '').getTime();
  return fetched.some((candidate) => {
    if (candidate.role !== 'user') return false;
    if (candidate.content === pending.content && sameAttachmentIds(candidate, pending)) return true;
    const candidateTime = parseServerTime(candidate.created_at || '').getTime();
    if (Number.isNaN(candidateTime) || Number.isNaN(pendingTime)) return false;
    return candidateTime >= pendingTime - 5000;
  });
}

function sameAttachmentIds(left: Message, right: Message): boolean {
  const leftIds = attachmentIds(left);
  const rightIds = attachmentIds(right);
  if (leftIds.length !== rightIds.length) return false;
  return leftIds.every((id, index) => id === rightIds[index]);
}

function attachmentIds(message: Message): string[] {
  const attachments = message.metadata?.attachments;
  if (!Array.isArray(attachments)) return [];
  return attachments
    .map((item) => (isRecord(item) && typeof item.id === 'string' ? item.id : ''))
    .filter(Boolean);
}

function upsertDraftMessage(messages: Message[], draft: Message): Message[] {
  if (messages.some((message) => message.message_id === draft.message_id || (draft.run_id && message.run_id === draft.run_id && message.role === 'assistant'))) {
    return messages;
  }
  return [...messages, draft];
}

function appendDraftDelta(messages: Message[], event: RuntimeEvent, delta: string, reasoningDelta: string): Message[] {
  return messages.map((message) => {
    if (!isMatchingDraft(message, event.run_id || '', event.message_id || '')) return message;
    const metadata = { ...(message.metadata || {}) };
    if (reasoningDelta) {
      metadata.reasoning_content = `${typeof metadata.reasoning_content === 'string' ? metadata.reasoning_content : ''}${reasoningDelta}`;
    }
    return { ...message, content: `${contentToDraftText(message.content)}${delta}`, metadata };
  });
}

function attachDraftMetrics(messages: Message[], event: RuntimeEvent): Message[] {
  const metrics = isRecord(event.payload.metrics) ? event.payload.metrics : undefined;
  if (!metrics) return messages;
  return messages.map((message) => {
    if (!isMatchingDraft(message, event.run_id || '', event.message_id || '')) return message;
    return { ...message, metadata: { ...(message.metadata || {}), llm_metrics: metrics } };
  });
}

function replaceDraftWithFinal(messages: Message[], finalMessage: Message, draftMessageId: string): Message[] {
  const withoutDuplicates = messages.filter((message) => {
    if (message.message_id === finalMessage.message_id) return false;
    if (draftMessageId && message.message_id === draftMessageId) return false;
    if (message.message_id.startsWith('draft-') && message.run_id && message.run_id === finalMessage.run_id) return false;
    return true;
  });
  return sortMessagesByCreatedAt([...withoutDuplicates, finalMessage]);
}

function removeDraftAndAppendError(messages: Message[], sessionId: string, runId: string, error: AppError): Message[] {
  const kept = messages.filter((message) => !(message.message_id.startsWith('draft-') && message.run_id === runId && !contentToDraftText(message.content)));
  return [...kept, createInlineErrorMessage(sessionId, error)];
}

function markDraftInterrupted(messages: Message[], runId: string): Message[] {
  if (!runId) return messages;
  return messages.map((message) => {
    if (!(message.message_id.startsWith('draft-') && message.run_id === runId)) return message;
    return {
      ...message,
      client_status: undefined,
      metadata: { ...(message.metadata || {}), interrupted: true, streaming: false },
    };
  });
}

function isMatchingDraft(message: Message, runId: string, messageId: string): boolean {
  if (!message.message_id.startsWith('draft-')) return false;
  if (messageId && message.message_id === messageId) return true;
  return Boolean(runId && message.run_id === runId);
}

function parseMessagePayload(value: unknown): Message | null {
  if (!isRecord(value)) return null;
  return value as Message;
}

function contentToDraftText(content: unknown): string {
  return typeof content === 'string' ? content : content == null ? '' : String(content);
}

function runningRunId(runs: Run[]): string | undefined {
  return [...runs].reverse().find((run) => run.status === 'RUNNING' || run.status === 'PENDING')?.run_id;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function chooseEnabledDefaultAgent(agents: Agent[], preferredAgentId?: string | null): string | undefined {
  const preferred = agents.find((agent) => agent.id === preferredAgentId && agent.enabled);
  return preferred?.id || agents.find((agent) => agent.enabled)?.id;
}

function sortSessionsByRecent(sessions: Session[]): Session[] {
  return sessions
    .map((session, index) => ({ session, index }))
    .sort((left, right) => {
      const leftTime = sessionSortTime(left.session);
      const rightTime = sessionSortTime(right.session);
      if (leftTime !== rightTime) return rightTime - leftTime;
      return left.index - right.index;
    })
    .map((item) => item.session);
}

function sessionSortTime(session: Session): number {
  const updated = parseServerTime(session.updated_at || '').getTime();
  if (!Number.isNaN(updated)) return updated;
  const created = parseServerTime(session.created_at || '').getTime();
  if (!Number.isNaN(created)) return created;
  return 0;
}

function newClientId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function formatError(error: unknown, fallback: string): { error: string; lastError: AppError } {
  if (error instanceof ApiError) {
    return {
      error: `${error.code}: ${error.message}`,
      lastError: { code: error.code, message: error.message, details: error.details },
    };
  }
  if (error instanceof Error) {
    return {
      error: error.message,
      lastError: { code: error.name || 'ERROR', message: error.message },
    };
  }
  return {
    error: fallback,
    lastError: { code: 'ERROR', message: fallback },
  };
}

function runtimeResultError(message: unknown, code: string): { error: string; lastError: AppError } {
  const text = typeof message === 'string' && message ? message : 'Run failed.';
  return {
    error: `${code}: ${text}`,
    lastError: { code, message: text },
  };
}
