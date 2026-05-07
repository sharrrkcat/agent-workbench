import type { Agent, CapabilityConfig, LlmDefaults, LlmProfile, LlmProviderStatus, Session } from '../types';

type ProfileState = Pick<WorkbenchLikeState, 'agents' | 'capabilityConfigs' | 'currentSession' | 'llmDefaults' | 'llmProfiles'>;

type WorkbenchLikeState = {
  agents: Agent[];
  capabilityConfigs: CapabilityConfig[];
  currentSession?: Session;
  llmDefaults?: LlmDefaults;
  llmProfiles: LlmProfile[];
};

export type ModelProfileStatusTone = 'green' | 'yellow' | 'red' | 'gray';

export type ModelProfileStatus = {
  code: string;
  tone: ModelProfileStatusTone;
  label: string;
  title: string;
};

export function resolveAgentDefaultLlmProfile(state: ProfileState, agentId?: string | null): LlmProfile | undefined {
  const agent = state.agents.find((item) => item.id === (agentId || state.currentSession?.default_agent_id));
  const agentProfileRef = agent?.resolved_runtime?.llm_profile_id || agent?.llm?.profile;
  return findEnabledProfile(state.llmProfiles, agentProfileRef);
}

export function resolveEffectiveInputLlmProfile(state: ProfileState): LlmProfile | undefined {
  const session = state.currentSession;
  const agent = state.agents.find((item) => item.id === session?.default_agent_id);
  const sessionAllowed = agent?.resolved_runtime?.allow_session_override !== false && agent?.llm?.allow_session_override !== false;
  if (sessionAllowed && session?.llm_profile_id) {
    const overrideProfile = findEnabledProfile(state.llmProfiles, session.llm_profile_id);
    if (overrideProfile) return overrideProfile;
  }
  return resolveAgentDefaultLlmProfile(state);
}

export function getModelProfileStatus(profile: LlmProfile | undefined, statuses: Record<string, LlmProviderStatus>): ModelProfileStatus {
  if (!profile) {
    return { code: 'NO_MODEL_PROFILE', tone: 'gray', label: 'No model', title: 'This agent has no model profile.' };
  }
  if (!profile.enabled) {
    return { code: 'MODEL_PROFILE_DISABLED', tone: 'red', label: 'Model disabled', title: 'Model profile is disabled.' };
  }
  if (!profile.provider_profile_id) {
    return { code: 'PROVIDER_PROFILE_MISSING', tone: 'red', label: 'Missing provider', title: 'Model profile has no provider profile.' };
  }
  const providerStatus = statuses[profile.provider_profile_id];
  if (!providerStatus) {
    return { code: 'MODEL_STATUS_UNKNOWN', tone: 'red', label: 'Unknown', title: 'Provider status has not been refreshed.' };
  }
  if (!providerStatus.reachable || providerStatus.status === 'PROVIDER_UNREACHABLE' || providerStatus.error) {
    return { code: 'PROVIDER_UNREACHABLE', tone: 'red', label: 'Unreachable', title: providerStatus.error?.message || 'Provider is unreachable.' };
  }
  const model = providerStatus.models.find((item) => item.id === profile.model_id);
  if (!model) {
    return { code: 'MODEL_NOT_AVAILABLE', tone: 'red', label: 'Model not found', title: 'Requested model was not found in the provider model list.' };
  }
  const code = model.status || providerStatus.status || 'MODEL_STATUS_UNKNOWN';
  if (code === 'READY' || model.loaded === true) {
    return { code: 'READY', tone: 'green', label: 'Ready', title: 'Provider is reachable and the model is loaded.' };
  }
  if (code === 'MODEL_NOT_LOADED' || model.loaded === false) {
    return { code: 'MODEL_NOT_LOADED', tone: 'yellow', label: 'Not loaded', title: 'Provider is reachable and the model exists, but it is not loaded.' };
  }
  if (code === 'MODEL_NOT_AVAILABLE' || code === 'MODEL_MISMATCH') {
    return { code, tone: 'red', label: code === 'MODEL_MISMATCH' ? 'Mismatch' : 'Model not found', title: 'Requested model is not available from this provider.' };
  }
  return { code, tone: 'red', label: 'Unknown', title: 'Model status is unknown.' };
}

export function modelStatusClass(status: ModelProfileStatus): string {
  if (status.tone === 'green') return 'ready';
  if (status.tone === 'yellow') return 'warning';
  if (status.tone === 'red') return 'error';
  return 'unknown';
}

export function statusPillClass(status: ModelProfileStatus): string {
  if (status.tone === 'green') return 'ok';
  if (status.tone === 'yellow') return 'warn';
  if (status.tone === 'red') return 'error';
  return '';
}

function findEnabledProfile(profiles: LlmProfile[], ref?: string | null): LlmProfile | undefined {
  if (!ref) return undefined;
  return profiles.find((profile) => profile.enabled && (profile.id === ref || profile.alias === ref));
}
