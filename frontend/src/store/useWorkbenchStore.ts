import { create } from 'zustand';
import { api } from '../api/client';
import type {
  Agent,
  AgentConfig,
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
  error?: string;
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

  initialize: async () => {
    set({ loading: true, error: undefined });
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
      set({ error: error instanceof Error ? error.message : 'Failed to initialize', loading: false });
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
      });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to update default agent' });
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
    set({ loading: true, error: undefined });
    try {
      await api.updateAgentConfig(agentId, patch);
      await get().refreshConfigs();
      set({ loading: false });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to update agent config', loading: false });
    }
  },

  updateCapabilityConfig: async (capabilityId, patch) => {
    set({ loading: true, error: undefined });
    try {
      await api.updateCapabilityConfig(capabilityId, patch);
      await get().refreshConfigs();
      set({ loading: false });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to update capability config', loading: false });
    }
  },

  getResolvedLlmConfig: async () => {
    try {
      return await api.getResolvedLlmConfig();
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to load LLM config status' });
      return null;
    }
  },

  testLlmConnection: async () => {
    set({ loading: true, error: undefined });
    try {
      const result = await api.testLlmConnection();
      set({ loading: false });
      return result;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'LLM test failed';
      set({ error: message, loading: false });
      return { success: false, message, base_url: '', error_code: 'LLM_CONNECTION_FAILED' };
    }
  },

  refreshHealth: async () => {
    try {
      const health = await api.getHealthDetails();
      set({ health });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to load backend health' });
    }
  },

  loadRunEvents: async (runId: string) => {
    set({ runEventLoading: runId, error: undefined });
    try {
      const events = await api.listRunEvents(runId);
      set({ runEvents: { ...get().runEvents, [runId]: events }, runEventLoading: undefined });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to load run timeline', runEventLoading: undefined });
    }
  },

  sendMessage: async (content: string) => {
    const session = get().currentSession;
    if (!session || !content.trim()) return;
    set({ loading: true, error: undefined });
    try {
      await api.sendMessage(session.session_id, content);
      await get().refreshCurrent();
      set({ loading: false });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Message failed', loading: false });
    }
  },

  invokeAction: async (action: AvailableAction) => {
    const session = get().currentSession;
    if (!session) return;
    set({ loading: true, error: undefined });
    try {
      await api.invokeAction(session.session_id, {
        agent_id: action.agent_id,
        action_id: action.action_id,
        source_message_id: action.source_message_id,
        prefill: action.prefill,
      });
      await get().refreshCurrent();
      set({ loading: false });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Action failed', loading: false });
    }
  },
}));
