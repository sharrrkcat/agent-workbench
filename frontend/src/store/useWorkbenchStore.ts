import { create } from 'zustand';
import { ApiError, api } from '../api/client';
import { resolveEffectiveInputLlmProfile } from '../utils/modelStatus';
import { parseServerTime } from '../utils/time';
import type {
  Agent,
  AgentConfig,
  AppError,
  AvailableAction,
  CapabilityConfig,
  Command,
  LlmResolvedConfig,
  LlmDefaults,
  GeneralSettings,
  LlmProfile,
  LlmProviderProfile,
  LlmProviderStatus,
  LlmTestResult,
  Message,
  Run,
  RunEvent,
  RunStep,
  RuntimeResponse,
  HealthDetails,
  RuntimeEvent,
  Session,
  SendMessageAttachment,
  ContextMode,
} from '../types';

type WorkbenchState = {
  agents: Agent[];
  commands: Command[];
  agentConfigs: AgentConfig[];
  capabilityConfigs: CapabilityConfig[];
  llmProfiles: LlmProfile[];
  llmProviderProfiles: LlmProviderProfile[];
  llmProviderStatuses: Record<string, LlmProviderStatus>;
  llmDefaults?: LlmDefaults;
  sessions: Session[];
  currentSession?: Session;
  messages: Message[];
  runs: Run[];
  runsById: Record<string, Run>;
  stepsByRunId: Record<string, RunStep[]>;
  runStepsExpandedByRunId: Record<string, boolean>;
  runEvents: Record<string, RunEvent[]>;
  lastMessageSeqById: Record<string, number>;
  completedMessageIds: Record<string, boolean>;
  health?: HealthDetails;
  generalSettings?: GeneralSettings;
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
  updateSessionContextMode: (contextMode: ContextMode) => Promise<void>;
  updateSessionLlmProfile: (profileId: string | null) => Promise<void>;
  refreshProviderStatuses: (providerProfileIds?: string[]) => Promise<void>;
  refreshCurrentResolvedProviderStatus: () => Promise<void>;
  refreshConfigs: () => Promise<void>;
  updateAgentConfig: (agentId: string, patch: Partial<Pick<AgentConfig, 'enabled' | 'user_config' | 'display' | 'runtime'>>) => Promise<void>;
  resetAgentOverrides: (agentId: string) => Promise<void>;
  writeAgentOverridesToManifest: (agentId: string) => Promise<void>;
  updateCapabilityConfig: (
    capabilityId: string,
    patch: Partial<Pick<CapabilityConfig, 'enabled' | 'user_config'>>,
  ) => Promise<void>;
  getResolvedLlmConfig: () => Promise<LlmResolvedConfig | null>;
  testLlmConnection: () => Promise<LlmTestResult>;
  refreshHealth: () => Promise<void>;
  refreshGeneralSettings: () => Promise<void>;
  updateGeneralSettings: (patch: Partial<GeneralSettings>) => Promise<void>;
  loadRunEvents: (runId: string) => Promise<void>;
  setRunStepsExpanded: (runId: string, expanded: boolean) => void;
  applyRuntimeEvent: (event: RuntimeEvent) => void;
  sendMessage: (content: string, attachments?: SendMessageAttachment[]) => Promise<boolean>;
  cancelActiveRun: () => Promise<void>;
  invokeAction: (action: AvailableAction) => Promise<void>;
  submitForm: (sourceMessageId: string, formId: string, values: Record<string, unknown>, options?: { silent?: boolean }) => Promise<RuntimeResponse | undefined>;
  deleteMessage: (messageId: string) => Promise<void>;
  dismissNotification: (notificationId: string) => Promise<void>;
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
  llmProviderProfiles: [],
  llmProviderStatuses: {},
  sessions: [],
  messages: [],
  runs: [],
  runsById: {},
  stepsByRunId: {},
  runStepsExpandedByRunId: {},
  runEvents: {},
  lastMessageSeqById: {},
  completedMessageIds: {},
  loading: false,
  creatingSession: false,
  sending: false,
  testingLlm: false,

  setError: (error, fallback) => set(formatError(error, fallback)),
  clearError: () => set({ error: undefined, lastError: undefined }),

  initialize: async () => {
    set({ loading: true, error: undefined, lastError: undefined });
    try {
      const [agents, commands, sessions, agentConfigs, capabilityConfigs, llmProfiles, llmProviderProfiles, llmDefaults, generalSettings] = await Promise.all([
        api.listAgents(),
        api.listCommands(),
        api.listSessions(),
        api.listAgentConfigs(),
        api.listCapabilityConfigs(),
        api.listLlmProfiles(),
        api.listLlmProviderProfiles(),
        api.getLlmDefaults(),
        api.getGeneralSettings(),
      ]);
      const sortedSessions = sortSessionsByRecent(sessions.map(normalizeSession));
      const currentSession = sortedSessions[0];
      set({ agents, commands, sessions: sortedSessions, currentSession, agentConfigs, capabilityConfigs, llmProfiles, llmProviderProfiles, llmDefaults, generalSettings, loading: false });
      if (currentSession) {
        await get().refreshCurrent();
        void get().refreshCurrentResolvedProviderStatus();
      }
      await get().refreshHealth();
    } catch (error) {
      set({ ...formatError(error, 'Failed to initialize'), loading: false });
    }
  },

  refreshCurrent: async () => {
    const session = get().currentSession;
    if (!session) return;
    const [freshSessionResponse, messages, runs] = await Promise.all([
      api.getSession(session.session_id),
      api.listMessages(session.session_id),
      api.listRuns(session.session_id),
    ]);
    const freshSession = normalizeSession(freshSessionResponse);
    if (get().currentSession?.session_id !== session.session_id) return;
    const sessions = (await api.listSessions()).map(normalizeSession);
    if (get().currentSession?.session_id !== session.session_id) return;
    const mergedRunState = mergeRunsIntoState(get(), runs);
    set({
      currentSession: freshSession,
      sessions: sortSessionsByRecent(sessions),
      messages: buildTimeline(messages, mergedRunState.runs, get().messages, session.session_id),
      runs: mergedRunState.runs,
      runsById: mergedRunState.runsById,
      stepsByRunId: mergedRunState.stepsByRunId,
      lastMessageSeqById: pruneStreamingSeqState(get().lastMessageSeqById, messages),
      completedMessageIds: pruneCompletedMessageState(get().completedMessageIds, messages),
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
      const session = normalizeSession(await api.createSession(`Session ${get().sessions.length + 1}`, defaultAgentId));
      const sessions = sortSessionsByRecent(await api.listSessions());
      set({ sessions: sessions.map(normalizeSession), currentSession: session, messages: [], runs: [], runsById: {}, stepsByRunId: {}, runStepsExpandedByRunId: {}, lastMessageSeqById: {}, completedMessageIds: {}, creatingSession: false });
    } catch (error) {
      set({ ...formatError(error, 'Failed to create session'), creatingSession: false });
    }
  },

  selectSession: async (sessionId: string) => {
    const session = normalizeSession(await api.getSession(sessionId));
    set({ currentSession: session, lastMessageSeqById: {}, completedMessageIds: {} });
    await get().refreshCurrent();
  },

  deleteSession: async (sessionId: string) => {
    const existingSessions = get().sessions;
    const deletingCurrent = get().currentSession?.session_id === sessionId;
    const nextSession = deletingCurrent ? existingSessions.find((session) => session.session_id !== sessionId) : undefined;

    try {
      await api.deleteSession(sessionId);
      if (deletingCurrent) {
        set({ currentSession: nextSession, messages: [], runs: [], runsById: {}, stepsByRunId: {}, runEvents: {}, runStepsExpandedByRunId: {}, lastMessageSeqById: {}, completedMessageIds: {} });
      }
      const sessions = sortSessionsByRecent((await api.listSessions()).map(normalizeSession).filter((session) => session.session_id !== sessionId));
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
          runsById: {},
          stepsByRunId: {},
          runStepsExpandedByRunId: {},
          runEvents: {},
          lastMessageSeqById: {},
          completedMessageIds: {},
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
        runsById: {},
        stepsByRunId: {},
        runStepsExpandedByRunId: {},
        runEvents: {},
        lastMessageSeqById: {},
        completedMessageIds: {},
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
      const updated = normalizeSession(await api.updateSession(sessionId, { title: trimmed }));
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
      const updated = normalizeSession(await api.updateSession(session.session_id, { default_agent_id: agentId }));
      set({
        currentSession: updated,
        sessions: sortSessionsByRecent(get().sessions.map((item) => (item.session_id === updated.session_id ? updated : item))),
        error: undefined,
        lastError: undefined,
      });
      void get().refreshCurrentResolvedProviderStatus();
    } catch (error) {
      set(formatError(error, 'Failed to update default agent'));
    }
  },

  updateSessionContextMode: async (contextMode: ContextMode) => {
    const session = get().currentSession;
    if (!session) return;
    if (normalizeContextMode(session.context_mode) === contextMode) return;
    try {
      const updated = normalizeSession(await api.updateSession(session.session_id, { context_mode: contextMode }));
      set({
        currentSession: updated,
        sessions: sortSessionsByRecent(get().sessions.map((item) => (item.session_id === updated.session_id ? updated : item))),
        error: undefined,
        lastError: undefined,
      });
      await get().refreshCurrent();
    } catch (error) {
      set(formatError(error, 'Failed to update conversation mode'));
      throw error;
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
      const updated = normalizeSession(await api.updateSession(session.session_id, { llm_profile_id: profileId }));
      set({
        currentSession: updated,
        sessions: sortSessionsByRecent(get().sessions.map((item) => (item.session_id === updated.session_id ? updated : item))),
        error: undefined,
        lastError: undefined,
      });
      void get().refreshCurrentResolvedProviderStatus();
    } catch (error) {
      set(formatError(error, 'Failed to update session model'));
    }
  },

  refreshProviderStatuses: async (providerProfileIds?: string[]) => {
    try {
      const result = await api.refreshLlmProviderStatuses(providerProfileIds);
      set({
        llmProviderStatuses: {
          ...get().llmProviderStatuses,
          ...Object.fromEntries(result.providers.map((provider) => [provider.provider_profile_id, provider])),
        },
        error: undefined,
        lastError: undefined,
      });
    } catch (error) {
      set(formatError(error, 'Failed to refresh provider status'));
    }
  },

  refreshCurrentResolvedProviderStatus: async () => {
    const profile = resolveCurrentLlmProfile(get());
    const providerId = profile?.provider_profile_id;
    if (!providerId) return;
    await get().refreshProviderStatuses([providerId]);
  },

  refreshConfigs: async () => {
    const [agents, commands, agentConfigs, capabilityConfigs, llmProfiles, llmProviderProfiles, llmDefaults] = await Promise.all([
      api.listAgents(),
      api.listCommands(),
      api.listAgentConfigs(),
      api.listCapabilityConfigs(),
      api.listLlmProfiles(),
      api.listLlmProviderProfiles(),
      api.getLlmDefaults(),
    ]);
    set({ agents, commands, agentConfigs, capabilityConfigs, llmProfiles, llmProviderProfiles, llmDefaults });
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

  resetAgentOverrides: async (agentId) => {
    set({ savingConfigId: `agent:${agentId}`, error: undefined, lastError: undefined });
    try {
      await api.resetAgentOverrides(agentId);
      await get().refreshConfigs();
      set({ savingConfigId: undefined });
    } catch (error) {
      set({ ...formatError(error, 'Failed to reset agent overrides'), savingConfigId: undefined });
      throw error;
    }
  },

  writeAgentOverridesToManifest: async (agentId) => {
    set({ savingConfigId: `agent:${agentId}`, error: undefined, lastError: undefined });
    try {
      await api.writeAgentOverridesToManifest(agentId);
      await get().refreshConfigs();
      set({ savingConfigId: undefined });
    } catch (error) {
      set({ ...formatError(error, 'Failed to write agent manifest'), savingConfigId: undefined });
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

  refreshGeneralSettings: async () => {
    try {
      const generalSettings = await api.getGeneralSettings();
      set({ generalSettings });
    } catch (error) {
      set(formatError(error, 'Failed to load general settings'));
    }
  },

  updateGeneralSettings: async (patch) => {
    try {
      const generalSettings = await api.updateGeneralSettings(patch);
      set({ generalSettings, error: undefined, lastError: undefined });
    } catch (error) {
      set(formatError(error, 'Failed to update general settings'));
      throw error;
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

  setRunStepsExpanded: (runId: string, expanded: boolean) => {
    if (!runId) return;
    set({ runStepsExpandedByRunId: { ...get().runStepsExpandedByRunId, [runId]: expanded } });
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
    if (event.type === 'llm_provider_status_updated') {
      const provider = parseLlmProviderStatusPayload(event.payload.provider);
      if (!provider) return;
      set({
        llmProviderStatuses: {
          ...get().llmProviderStatuses,
          [provider.provider_profile_id]: provider,
        },
      });
      return;
    }
    if (event.type === 'run_started' && event.run_id) {
      set({ activeRunId: event.run_id, sending: true });
      return;
    }
    if (event.type === 'session_updated') {
      const updatedSession = parseSessionPayload(event.payload.session);
      if (updatedSession) {
        set({
          currentSession: get().currentSession?.session_id === updatedSession.session_id ? updatedSession : get().currentSession,
          sessions: sortSessionsByRecent(get().sessions.map((item) => (item.session_id === updatedSession.session_id ? updatedSession : item))),
        });
      }
      return;
    }
    if ((event.type === 'run_updated' || event.type === 'run_created' || event.type === 'run_cancel_requested' || event.type === 'run_completed') && event.run_id) {
      const run = parseRunPayload(event.payload.run) || runFromEvent(event, session.session_id);
      const mergedRunState = mergeRunsIntoState(get(), [run]);
      set({
        runs: mergedRunState.runs,
        runsById: mergedRunState.runsById,
        stepsByRunId: mergedRunState.stepsByRunId,
        messages: attachRunToMessages(get().messages, mergedRunState.runsById[run.run_id] || run, mergedRunState.stepsByRunId),
        sending: isRunActive(run.status) ? true : get().sending,
        activeRunId: isRunActive(run.status) ? run.run_id : get().activeRunId,
      });
      if (event.type === 'run_completed') {
        set({ sending: false, activeRunId: undefined });
      }
      return;
    }
    if ((event.type === 'run_step_created' || event.type === 'run_step_updated') && event.run_id) {
      const step = parseRunStepPayload(event.payload.step);
      if (!step) return;
      const mergedRunState = mergeRunStepIntoState(get(), step);
      set({
        runs: mergedRunState.runs,
        runsById: mergedRunState.runsById,
        stepsByRunId: mergedRunState.stepsByRunId,
        messages: upsertMessageRunStep(get().messages, step, mergedRunState.runs, mergedRunState.stepsByRunId),
      });
      return;
    }
    if (event.type === 'message_started' && event.run_id) {
      const draft = createDraftAssistantMessage(session.session_id, event);
      set({
        activeRunId: event.run_id,
        sending: true,
        messages: upsertDraftMessage(get().messages, draft),
        lastMessageSeqById: clearStreamingSeq(get().lastMessageSeqById, draft.message_id),
        completedMessageIds: clearCompletedMessage(get().completedMessageIds, draft.message_id),
      });
      return;
    }
    if (event.type === 'message_delta' && event.run_id) {
      const delta = typeof event.payload.delta === 'string' ? event.payload.delta : '';
      const reasoningDelta = typeof event.payload.reasoning_delta === 'string' ? event.payload.reasoning_delta : '';
      if (!delta && !reasoningDelta) return;
      const seq = eventSeq(event);
      if (seq === null) return;
      const seqKey = resolveMessageSeqKey(get().messages, event);
      if (!seqKey) return;
      const lastSeq = get().lastMessageSeqById[seqKey] || 0;
      if (get().completedMessageIds[seqKey] && seq <= lastSeq) return;
      if (seq <= lastSeq) return;
      set({
        messages: appendDraftDelta(get().messages, event, delta, reasoningDelta),
        lastMessageSeqById: { ...get().lastMessageSeqById, [seqKey]: seq },
      });
      return;
    }
    if (event.type === 'message_updated') {
      const updatedMessage = parseMessagePayload(event.payload.message);
      if (updatedMessage) {
        set({ messages: mergeUpdatedMessage(get().messages, updatedMessage, get().completedMessageIds) });
      }
      return;
    }
    if (event.type === 'message_completed') {
      const finalMessage = parseMessagePayload(event.payload.message);
      if (finalMessage) {
        const seq = eventSeq(event);
        const draftMessageId = String(event.payload.draft_message_id || '');
        const lastSeq = Math.max(get().lastMessageSeqById[finalMessage.message_id] || 0, draftMessageId ? get().lastMessageSeqById[draftMessageId] || 0 : 0);
        if (seq !== null && seq < lastSeq) return;
        const nextSeq = seq ?? lastSeq;
        set({
          messages: replaceDraftWithFinal(get().messages, finalMessage, draftMessageId),
          lastMessageSeqById: markMessageSeq(get().lastMessageSeqById, [finalMessage.message_id, draftMessageId], nextSeq),
          completedMessageIds: markCompletedMessages(get().completedMessageIds, [finalMessage.message_id, draftMessageId]),
        });
      }
      return;
    }
    if (event.type === 'run_metrics') {
      set({ messages: attachDraftMetrics(get().messages, event) });
      return;
    }
    if (event.type === 'run_failed') {
      const code = typeof event.payload.error_code === 'string' ? event.payload.error_code : 'RUN_FAILED';
      const error = {
        code,
        message: typeof event.payload.error === 'string' ? event.payload.error : 'Run failed.',
      };
      const runs = upsertRun(get().runs, parseRunPayload(event.payload.run) || failedRunFromEvent(event, session.session_id, error));
      const mergedRunState = mergeRunsIntoState(get(), runs);
      set({
        sending: false,
        activeRunId: undefined,
        runs: mergedRunState.runs,
        runsById: mergedRunState.runsById,
        stepsByRunId: mergedRunState.stepsByRunId,
        messages: buildTimeline(get().messages, mergedRunState.runs, get().messages, session.session_id),
      });
      return;
    }
    if (event.type === 'run_cancelled') {
      const run = parseRunPayload(event.payload.run);
      const mergedRunState = run ? mergeRunsIntoState(get(), [run]) : pickRunState(get());
      set({
        sending: false,
        activeRunId: undefined,
        runs: mergedRunState.runs,
        runsById: mergedRunState.runsById,
        stepsByRunId: mergedRunState.stepsByRunId,
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

  submitForm: async (sourceMessageId: string, formId: string, values: Record<string, unknown>, options?: { silent?: boolean }) => {
    const session = get().currentSession;
    if (!session) return;
    const key = `${sourceMessageId}:form:${formId}`;
    set({ pendingActionKey: key, error: undefined, lastError: undefined });
    try {
      const result = await api.submitForm(session.session_id, {
        source_message_id: sourceMessageId,
        form_id: formId,
        values,
      });
      if (result.updated_form) {
        set({ messages: applyUpdatedFormBlock(get().messages, result.updated_form) });
      }
      await get().refreshCurrent();
      if (!result.success) {
        set({ error: undefined, lastError: undefined });
      }
      set({ pendingActionKey: undefined });
      return result;
    } catch (error) {
      const formatted = formatError(error, 'Form submission failed');
      if (options?.silent) {
        set({ error: undefined, lastError: undefined, pendingActionKey: undefined });
      } else {
        set({
          error: undefined,
          lastError: undefined,
          pendingActionKey: undefined,
          messages: [...get().messages, createInlineErrorMessage(session.session_id, formatted.lastError, sourceMessageId)],
        });
      }
      throw error;
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

  dismissNotification: async (notificationId: string) => {
    const session = get().currentSession;
    if (!session) return;
    set({ pendingMessageActionId: notificationId, error: undefined, lastError: undefined });
    try {
      await api.dismissNotification(session.session_id, notificationId);
      set({
        pendingMessageActionId: undefined,
        messages: get().messages.filter((message) => message.message_id !== notificationId),
        runs: get().runs.map((run) =>
          runErrorMessageId(run.run_id) === notificationId
            ? { ...run, metadata: { ...(run.metadata || {}), notification_dismissed: true } }
            : run,
        ),
        error: undefined,
        lastError: undefined,
      });
    } catch (error) {
      set({ ...formatError(error, 'Failed to delete notification'), pendingMessageActionId: undefined });
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
    action_id: typeof payload.action_id === 'string' ? payload.action_id : 'default',
    run_id: event.run_id || null,
    output_type: 'text',
    parent_message_id: typeof payload.parent_message_id === 'string' ? payload.parent_message_id : null,
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
  const baseMessages = sortMessagesByCreatedAt(removeSupersededFailedDrafts(fetchedMessages, runs));
  const messages = sortTimelineItems(baseMessages, failedRunErrors(baseMessages, runs, sessionId));
  return mergeTransientMessages(messages, current, sessionId);
}

function pickRunState(state: Pick<WorkbenchState, 'runs' | 'runsById' | 'stepsByRunId'>): Pick<WorkbenchState, 'runs' | 'runsById' | 'stepsByRunId'> {
  return {
    runs: state.runs,
    runsById: state.runsById,
    stepsByRunId: state.stepsByRunId,
  };
}

function mergeRunsIntoState(state: Pick<WorkbenchState, 'runs' | 'runsById' | 'stepsByRunId'>, incomingRuns: Run[]): Pick<WorkbenchState, 'runs' | 'runsById' | 'stepsByRunId'> {
  const stepsByRunId = { ...state.stepsByRunId };
  const runsById = { ...state.runsById };
  for (const run of incomingRuns) {
    if (!run.run_id) continue;
    const mergedSteps = mergeRunSteps(stepsByRunId[run.run_id] || runsById[run.run_id]?.steps || [], run.steps || []);
    stepsByRunId[run.run_id] = mergedSteps;
    runsById[run.run_id] = {
      ...(runsById[run.run_id] || {}),
      ...run,
      steps: mergedSteps,
      metadata: { ...(runsById[run.run_id]?.metadata || {}), ...(run.metadata || {}) },
    };
  }
  const mergedRuns = dedupeRuns([...state.runs, ...incomingRuns]).map((run) => runsById[run.run_id] || run);
  return { runs: mergedRuns, runsById, stepsByRunId };
}

function mergeRunStepIntoState(state: Pick<WorkbenchState, 'runs' | 'runsById' | 'stepsByRunId'>, step: RunStep): Pick<WorkbenchState, 'runs' | 'runsById' | 'stepsByRunId'> {
  const stepsByRunId = {
    ...state.stepsByRunId,
    [step.run_id]: mergeRunSteps(state.stepsByRunId[step.run_id] || state.runsById[step.run_id]?.steps || [], [step]),
  };
  const runsById = { ...state.runsById };
  if (runsById[step.run_id]) {
    runsById[step.run_id] = { ...runsById[step.run_id], steps: stepsByRunId[step.run_id] };
  }
  const runs = state.runs.map((run) => (run.run_id === step.run_id ? { ...run, steps: stepsByRunId[step.run_id] } : run));
  return { runs, runsById, stepsByRunId };
}

function failedRunErrors(messages: Message[], runs: Run[], sessionId: string): Message[] {
  const messageRunIds = new Set(messages.filter((message) => !isTransientMessage(message)).map((message) => message.run_id).filter(isNonEmptyString));
  const seenRunIds = new Set<string>();
  return dedupeRuns(runs)
    .filter((run) => {
      if (run.session_id !== sessionId) return false;
      if (
        run.status !== 'FAILED' ||
        !run.error ||
        !run.run_id ||
        run.metadata?.notification_dismissed === true ||
        messageRunIds.has(run.run_id) ||
        seenRunIds.has(run.run_id)
      ) {
        return false;
      }
      seenRunIds.add(run.run_id);
      return true;
    })
    .map((run) => {
      const parentMessageId = firstString(run.metadata, ['parent_message_id', 'input_message_id', 'source_message_id']);
      const relatedMessage = parentMessageId ? messages.find((message) => message.message_id === parentMessageId) : undefined;
      return {
        message_id: runErrorMessageId(run.run_id),
        session_id: run.session_id,
        role: 'system',
        content: { code: failedRunCode(run), message: run.error || 'Run failed.' },
        agent_id: null,
        command_name: null,
        action_id: run.action_id,
        run_id: run.run_id,
        run,
        run_steps: run.steps || [],
        output_type: 'error',
        parent_message_id: parentMessageId,
        metadata: { synthetic: true, notification: true, severity: 'error', run_kind: run.kind, target_id: run.target_id },
        available_actions: [],
        created_at: run.created_at || run.updated_at || relatedMessage?.created_at || stableNotificationFallback(run),
        client_status: 'failed',
        client_error: { code: failedRunCode(run), message: run.error || 'Run failed.' },
      } satisfies Message;
    });
}

function removeSupersededFailedDrafts(messages: Message[], runs: Run[]): Message[] {
  const failedRunIds = new Set(runs.filter((run) => run.status === 'FAILED').map((run) => run.run_id).filter(isNonEmptyString));
  if (!failedRunIds.size) return messages;
  return messages.filter((message) => {
    if (!message.run_id || !failedRunIds.has(message.run_id) || !message.message_id.startsWith('draft-')) return true;
    return Boolean(contentToDraftText(message.content));
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
      const leftRank = timelineTieRank(left.message);
      const rightRank = timelineTieRank(right.message);
      if (leftRank !== rightRank) return leftRank - rightRank;
      return left.index - right.index;
    })
    .map((item) => item.message);
}

function sortTimelineItems(messages: Message[], notifications: Message[]): Message[] {
  if (!notifications.length) return messages;
  const sequence = new Map<string, number>();
  messages.forEach((message, index) => sequence.set(message.message_id, index * 2));
  const sortable = [
    ...messages.map((message) => ({ message, sequence: sequence.get(message.message_id) || 0 })),
    ...notifications.map((message, index) => ({
      message,
      sequence:
        (message.parent_message_id && sequence.has(message.parent_message_id)
          ? Number(sequence.get(message.parent_message_id)) + 1
          : undefined) ?? (messages.length + index) * 2 + 1,
    })),
  ];
  return sortable
    .sort((left, right) => {
      const leftTime = parseServerTime(left.message.created_at || '').getTime();
      const rightTime = parseServerTime(right.message.created_at || '').getTime();
      const normalizedLeft = Number.isNaN(leftTime) ? 0 : leftTime;
      const normalizedRight = Number.isNaN(rightTime) ? 0 : rightTime;
      if (normalizedLeft !== normalizedRight) return normalizedLeft - normalizedRight;
      if (left.sequence !== right.sequence) return left.sequence - right.sequence;
      return timelineTieRank(left.message) - timelineTieRank(right.message);
    })
    .map((item) => item.message);
}

function timelineTieRank(message: Message): number {
  if (message.role === 'user') return 0;
  if (message.role === 'assistant' || message.role === 'agent') return 1;
  if (isRunFailedErrorMessage(message)) return 2;
  return 3;
}

function stableNotificationFallback(run: Run): string {
  const offset = parseInt(hashString(run.run_id || `${run.session_id}:${run.error || ''}`), 36) % (365 * 24 * 60 * 60 * 1000);
  return new Date(Date.UTC(2000, 0, 1) + offset).toISOString();
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
  const fetchedMessageIds = new Set(fetched.map((message) => message.message_id));
  const remaining = transient.filter((message) => {
    if (fetchedMessageIds.has(message.message_id)) return false;
    if (isRunFailedErrorMessage(message)) return false;
    if (message.run_id && fetchedRunIds.has(message.run_id)) return false;
    if (message.role === 'user' && message.client_status === 'pending' && hasFetchedReplacementUser(fetched, message)) return false;
    if (message.role !== 'user') return true;
    return !fetched.some((candidate) => candidate.role === 'user' && candidate.content === message.content && sameAttachmentIds(candidate, message));
  });

  return [...fetched, ...remaining];
}

function isTransientMessage(message: Message): boolean {
  return message.message_id.startsWith('optimistic-') || message.message_id.startsWith('error-') || message.message_id.startsWith('draft-') || message.message_id.startsWith('run-error:');
}

function isRunFailedErrorMessage(message: Message): boolean {
  if (message.message_id.startsWith('run-error:')) return true;
  if (message.client_error?.code === 'RUN_FAILED') return true;
  if (!isRecord(message.content)) return false;
  return message.content.code === 'RUN_FAILED';
}

function runErrorMessageId(runId: string): string {
  return `run-error:${runId}`;
}

function failedRunCode(run: Run): string {
  const error = run.metadata?.error;
  if (isRecord(error) && typeof error.code === 'string') return error.code;
  return 'RUN_FAILED';
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
  let replaced = false;
  const next = messages.map((message) => {
    const sameDraft = message.message_id === draft.message_id || (draft.run_id && message.run_id === draft.run_id && message.role === 'assistant' && message.message_id.startsWith('draft-'));
    if (!sameDraft) return message;
    replaced = true;
    return {
      ...message,
      agent_id: message.agent_id || draft.agent_id,
      action_id: message.action_id || draft.action_id,
      parent_message_id: message.parent_message_id || draft.parent_message_id,
      metadata: { ...(message.metadata || {}), ...(draft.metadata || {}) },
      client_status: message.client_status || draft.client_status,
    };
  });
  if (replaced) {
    return next;
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

function mergeUpdatedMessage(messages: Message[], updatedMessage: Message, completedMessageIds: Record<string, boolean> = {}): Message[] {
  let replaced = false;
  const next = messages.map((message) => {
    const sameMessage = message.message_id === updatedMessage.message_id;
    const sameRunDraft = message.message_id.startsWith('draft-') && message.run_id && message.run_id === updatedMessage.run_id;
    if (!sameMessage && !sameRunDraft) return message;
    replaced = true;
    const preserveStreamingContent = message.client_status === 'streaming' || completedMessageIds[message.message_id] || completedMessageIds[updatedMessage.message_id];
    return {
      ...message,
      ...updatedMessage,
      content: preserveStreamingContent ? message.content : updatedMessage.content,
      run: message.run || updatedMessage.run,
      run_steps: mergeRunSteps(message.run_steps || [], updatedMessage.run_steps || updatedMessage.run?.steps || []),
      metadata: { ...(message.metadata || {}), ...(updatedMessage.metadata || {}) },
      client_status: updatedMessage.metadata?.streaming === false ? undefined : message.client_status,
    };
  });
  return replaced ? sortMessagesByCreatedAt(next) : sortMessagesByCreatedAt([...messages, updatedMessage]);
}

function applyUpdatedFormBlock(messages: Message[], updatedForm: NonNullable<RuntimeResponse['updated_form']>): Message[] {
  return messages.map((message) => {
    if (message.message_id !== updatedForm.source_message_id) return message;
    const content = replaceActionFormBlock(message.content, updatedForm.form_id, updatedForm.block);
    return content === message.content ? message : { ...message, content };
  });
}

function replaceActionFormBlock(content: unknown, formId: string, block: unknown): unknown {
  if (!isRecord(content)) return content;
  if (content.type === 'action_form' && content.form_id === formId) {
    return block;
  }
  if (!Array.isArray(content.blocks)) return content;
  let replaced = false;
  const blocks = content.blocks.map((item) => {
    if (isRecord(item) && item.type === 'action_form' && item.form_id === formId) {
      replaced = true;
      return block;
    }
    return item;
  });
  return replaced ? { ...content, blocks } : content;
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
  if (!message.message_id.startsWith('draft-') && message.client_status !== 'streaming') return false;
  if (messageId && message.message_id === messageId) return true;
  return Boolean(runId && message.run_id === runId);
}

function eventSeq(event: RuntimeEvent): number | null {
  const seq = event.payload.seq;
  return typeof seq === 'number' && Number.isFinite(seq) ? seq : null;
}

function resolveMessageSeqKey(messages: Message[], event: RuntimeEvent): string {
  if (typeof event.message_id === 'string' && event.message_id) return event.message_id;
  const match = messages.find((message) => isMatchingDraft(message, event.run_id || '', ''));
  return match?.message_id || '';
}

function markMessageSeq(current: Record<string, number>, messageIds: string[], seq: number): Record<string, number> {
  const next = { ...current };
  for (const messageId of messageIds) {
    if (messageId) next[messageId] = Math.max(next[messageId] || 0, seq);
  }
  return next;
}

function markCompletedMessages(current: Record<string, boolean>, messageIds: string[]): Record<string, boolean> {
  const next = { ...current };
  for (const messageId of messageIds) {
    if (messageId) next[messageId] = true;
  }
  return next;
}

function clearStreamingSeq(current: Record<string, number>, messageId: string): Record<string, number> {
  if (!messageId || !(messageId in current)) return current;
  const next = { ...current };
  delete next[messageId];
  return next;
}

function clearCompletedMessage(current: Record<string, boolean>, messageId: string): Record<string, boolean> {
  if (!messageId || !(messageId in current)) return current;
  const next = { ...current };
  delete next[messageId];
  return next;
}

function pruneStreamingSeqState(current: Record<string, number>, messages: Message[]): Record<string, number> {
  const messageIds = new Set(messages.map((message) => message.message_id));
  return Object.fromEntries(Object.entries(current).filter(([messageId]) => messageIds.has(messageId)));
}

function pruneCompletedMessageState(current: Record<string, boolean>, messages: Message[]): Record<string, boolean> {
  const messageIds = new Set(messages.map((message) => message.message_id));
  return Object.fromEntries(Object.entries(current).filter(([messageId]) => messageIds.has(messageId)));
}

function parseMessagePayload(value: unknown): Message | null {
  if (!isRecord(value)) return null;
  return value as Message;
}

function parseLlmProviderStatusPayload(value: unknown): LlmProviderStatus | null {
  if (!isRecord(value) || typeof value.provider_profile_id !== 'string') return null;
  return value as LlmProviderStatus;
}

function contentToDraftText(content: unknown): string {
  return typeof content === 'string' ? content : content == null ? '' : String(content);
}

function runningRunId(runs: Run[]): string | undefined {
  return [...runs].reverse().find((run) => isRunActive(run.status))?.run_id;
}

function isRunActive(status: string): boolean {
  return ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(status);
}

function upsertRun(runs: Run[], run: Run): Run[] {
  const index = runs.findIndex((item) => item.run_id === run.run_id);
  if (index === -1) return [...runs, run];
  return runs.map((item, itemIndex) =>
    itemIndex === index
      ? { ...item, ...run, steps: mergeRunSteps(item.steps || [], run.steps || []), metadata: { ...(item.metadata || {}), ...(run.metadata || {}) } }
      : item,
  );
}

function upsertRunStep(runs: Run[], step: RunStep): Run[] {
  const existing = runs.find((run) => run.run_id === step.run_id);
  if (!existing) {
    return runs;
  }
  return runs.map((run) => (run.run_id === step.run_id ? { ...run, steps: mergeRunSteps(run.steps || [], [step]) } : run));
}

function mergeRunSteps(left: RunStep[], right: RunStep[]): RunStep[] {
  const byId = new Map<string, RunStep>();
  for (const step of [...left, ...right]) {
    if (!step.step_id) continue;
    byId.set(step.step_id, { ...(byId.get(step.step_id) || {}), ...step });
  }
  return [...byId.values()].sort((a, b) => (a.order ?? 0) - (b.order ?? 0) || parseServerTime(a.created_at).getTime() - parseServerTime(b.created_at).getTime());
}

function attachRunToMessages(messages: Message[], run: Run, stepsByRunId: Record<string, RunStep[]>): Message[] {
  return messages.map((message) =>
    message.run_id === run.run_id ? { ...message, run, run_steps: mergeRunSteps(message.run_steps || [], stepsByRunId[run.run_id] || run.steps || []) } : message,
  );
}

function upsertMessageRunStep(messages: Message[], step: RunStep, runs: Run[], stepsByRunId: Record<string, RunStep[]>): Message[] {
  const run = runs.find((item) => item.run_id === step.run_id);
  return messages.map((message) => {
    if (message.run_id !== step.run_id) return message;
    return { ...message, run: run || message.run, run_steps: mergeRunSteps(message.run_steps || [], stepsByRunId[step.run_id] || [step]) };
  });
}

function parseRunPayload(value: unknown): Run | null {
  if (!isRecord(value) || typeof value.run_id !== 'string') return null;
  return value as Run;
}

function parseRunStepPayload(value: unknown): RunStep | null {
  if (!isRecord(value) || typeof value.step_id !== 'string' || typeof value.run_id !== 'string') return null;
  return value as RunStep;
}

function runFromEvent(event: RuntimeEvent, sessionId: string): Run {
  const existing = event.run_id ? getCurrentRun(event.run_id) : undefined;
  return {
    run_id: event.run_id || fallbackRunId(sessionId, event.created_at, event.type),
    session_id: sessionId,
    kind: existing?.kind || 'agent',
    status: event.type === 'run_completed' ? 'DONE' : event.type === 'run_cancel_requested' ? 'CANCELLING' : 'RUNNING',
    target_id: existing?.target_id || stringPayload(event.payload, 'target_id') || 'unknown',
    action_id: existing?.action_id || stringPayload(event.payload, 'action_id') || null,
    current_step: stringPayload(event.payload, 'stage') || existing?.current_step || '',
    metadata: existing?.metadata || {},
    steps: existing?.steps || [],
    created_at: existing?.created_at || event.created_at,
    updated_at: event.created_at,
  };
}

function dedupeRuns(runs: Run[]): Run[] {
  const byId = new Map<string, Run>();
  for (const run of runs) {
    if (!run.run_id) continue;
    byId.set(run.run_id, { ...(byId.get(run.run_id) || {}), ...run, metadata: { ...(byId.get(run.run_id)?.metadata || {}), ...(run.metadata || {}) } });
  }
  return [...byId.values()];
}

function failedRunFromEvent(event: RuntimeEvent, sessionId: string, error: AppError): Run {
  const runId = event.run_id || fallbackRunId(sessionId, event.created_at, error.message);
  const existing = getCurrentRun(runId);
  return {
    run_id: runId,
    session_id: sessionId,
    kind: existing?.kind || 'agent',
    status: 'FAILED',
    target_id: existing?.target_id || stringPayload(event.payload, 'target_id') || 'unknown',
    action_id: existing?.action_id || stringPayload(event.payload, 'action_id') || null,
    current_step: 'failed',
    error: error.message,
    metadata: {
      ...(existing?.metadata || {}),
      error: { code: error.code, message: error.message, details: event.payload.details },
      parent_message_id: stringPayload(event.payload, 'parent_message_id') || existing?.metadata?.parent_message_id,
      input_message_id: stringPayload(event.payload, 'input_message_id') || existing?.metadata?.input_message_id,
      source_message_id: stringPayload(event.payload, 'source_message_id') || existing?.metadata?.source_message_id,
    },
    created_at: existing?.created_at || stringPayload(event.payload, 'created_at') || event.created_at,
    updated_at: event.created_at,
  };
}

function getCurrentRun(runId: string): Run | undefined {
  return useWorkbenchStore.getState().runs.find((run) => run.run_id === runId);
}

function stringPayload(payload: Record<string, unknown>, key: string): string | undefined {
  const value = payload[key];
  return typeof value === 'string' && value ? value : undefined;
}

function fallbackRunId(sessionId: string, createdAt: string, error: string): string {
  return `${sessionId}:${createdAt}:${hashString(error)}`;
}

function hashString(value: string): string {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) | 0;
  }
  return Math.abs(hash).toString(36);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && Boolean(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function chooseEnabledDefaultAgent(agents: Agent[], preferredAgentId?: string | null): string | undefined {
  const preferred = agents.find((agent) => agent.id === preferredAgentId && agent.enabled);
  return preferred?.id || agents.find((agent) => agent.enabled)?.id;
}

export function resolveCurrentLlmProfile(state: Pick<WorkbenchState, 'currentSession' | 'agents' | 'llmProfiles' | 'llmDefaults' | 'capabilityConfigs'>): LlmProfile | undefined {
  return resolveEffectiveInputLlmProfile(state);
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

function normalizeSession(session: Session): Session {
  return { ...session, context_mode: normalizeContextMode(session.context_mode) };
}

function parseSessionPayload(value: unknown): Session | null {
  if (!value || typeof value !== 'object') return null;
  const session = value as Partial<Session>;
  if (typeof session.session_id !== 'string') return null;
  return normalizeSession(session as Session);
}

function normalizeContextMode(contextMode?: string | null): ContextMode {
  return contextMode === 'group_transcript' ? 'group_transcript' : 'single_assistant';
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
