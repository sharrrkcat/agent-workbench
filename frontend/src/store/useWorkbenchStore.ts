import { create } from 'zustand';
import { ApiError, api } from '../api/client';
import type {
  Agent,
  AgentConfig,
  AppError,
  AvailableAction,
  CapabilityConfig,
  Command,
  LlmResolvedConfig,
  LlmTestResult,
  Message,
  Run,
  RunEvent,
  HealthDetails,
  Session,
} from '../types';

type WorkbenchState = {
  agents: Agent[];
  commands: Command[];
  agentConfigs: AgentConfig[];
  capabilityConfigs: CapabilityConfig[];
  sessions: Session[];
  currentSession?: Session;
  messages: Message[];
  runs: Run[];
  runEvents: Record<string, RunEvent[]>;
  health?: HealthDetails;
  runEventLoading?: string;
  loading: boolean;
  sending: boolean;
  savingConfigId?: string;
  testingLlm: boolean;
  pendingActionKey?: string;
  error?: string;
  lastError?: AppError;
  setError: (error: unknown, fallback: string) => void;
  clearError: () => void;
  initialize: () => Promise<void>;
  refreshCurrent: () => Promise<void>;
  createSession: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  updateDefaultAgent: (agentId: string) => Promise<void>;
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
  sendMessage: (content: string) => Promise<void>;
  invokeAction: (action: AvailableAction) => Promise<void>;
};

export const actionKey = (action: AvailableAction) => `${action.source_message_id}-${action.agent_id}-${action.action_id}`;

export const useWorkbenchStore = create<WorkbenchState>((set, get) => ({
  agents: [],
  commands: [],
  agentConfigs: [],
  capabilityConfigs: [],
  sessions: [],
  messages: [],
  runs: [],
  runEvents: {},
  loading: false,
  sending: false,
  testingLlm: false,

  setError: (error, fallback) => set(formatError(error, fallback)),
  clearError: () => set({ error: undefined, lastError: undefined }),

  initialize: async () => {
    set({ loading: true, error: undefined, lastError: undefined });
    try {
      const [agents, commands, sessions, agentConfigs, capabilityConfigs] = await Promise.all([
        api.listAgents(),
        api.listCommands(),
        api.listSessions(),
        api.listAgentConfigs(),
        api.listCapabilityConfigs(),
      ]);
      const currentSession = sessions[0];
      set({ agents, commands, sessions, currentSession, agentConfigs, capabilityConfigs, loading: false });
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
    set({ currentSession: freshSession, messages, runs });
  },

  createSession: async () => {
    const session = await api.createSession(`Session ${get().sessions.length + 1}`, get().currentSession?.default_agent_id || 'chat');
    set({ sessions: [session, ...get().sessions], currentSession: session, messages: [], runs: [] });
  },

  selectSession: async (sessionId: string) => {
    const session = await api.getSession(sessionId);
    set({ currentSession: session });
    await get().refreshCurrent();
  },

  updateDefaultAgent: async (agentId: string) => {
    const session = get().currentSession;
    if (!session) return;
    try {
      const updated = await api.updateSession(session.session_id, { default_agent_id: agentId });
      set({
        currentSession: updated,
        sessions: get().sessions.map((item) => (item.session_id === updated.session_id ? updated : item)),
        error: undefined,
        lastError: undefined,
      });
    } catch (error) {
      set(formatError(error, 'Failed to update default agent'));
    }
  },

  refreshConfigs: async () => {
    const [agents, commands, agentConfigs, capabilityConfigs] = await Promise.all([
      api.listAgents(),
      api.listCommands(),
      api.listAgentConfigs(),
      api.listCapabilityConfigs(),
    ]);
    set({ agents, commands, agentConfigs, capabilityConfigs });
  },

  updateAgentConfig: async (agentId, patch) => {
    set({ savingConfigId: `agent:${agentId}`, error: undefined, lastError: undefined });
    try {
      await api.updateAgentConfig(agentId, patch);
      await get().refreshConfigs();
      set({ savingConfigId: undefined });
    } catch (error) {
      set({ ...formatError(error, 'Failed to update agent config'), savingConfigId: undefined });
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

  sendMessage: async (content: string) => {
    const session = get().currentSession;
    if (!session || !content.trim() || get().sending) return;
    set({ sending: true, error: undefined, lastError: undefined });
    try {
      const result = await api.sendMessage(session.session_id, content);
      await get().refreshCurrent();
      if (!result.success) {
        set(runtimeResultError(result.error, 'RUN_FAILED'));
      }
      set({ sending: false });
    } catch (error) {
      set({ ...formatError(error, 'Message failed'), sending: false });
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
        set(runtimeResultError(result.error, 'ACTION_FAILED'));
      }
      set({ pendingActionKey: undefined });
    } catch (error) {
      set({ ...formatError(error, 'Action failed'), pendingActionKey: undefined });
    }
  },
}));

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
