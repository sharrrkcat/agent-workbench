import type { Agent, AgentConfig, AvatarType, LlmProfile, ManifestSummary, ResolvedAgentDisplay } from '../types';
import type { TFunction } from 'i18next';

export type AgentDisplaySource = Pick<Agent, 'id' | 'name' | 'avatar' | 'avatar_type' | 'avatar_url' | 'resolved_display' | 'resolved_runtime' | 'llm' | 'model' | 'type' | 'capabilities'> | AgentConfig | ManifestSummary;

export type ResolvedAgentDisplayView = {
  id: string;
  name: string;
  description: string;
  avatar?: string | null;
  avatar_type?: AvatarType;
  avatar_url?: string | null;
};

export function getResolvedAgentDisplay(source?: AgentDisplaySource | null): ResolvedAgentDisplayView {
  if (!source) {
    return { id: '', name: 'AI', description: '', avatar: null, avatar_type: 'initials', avatar_url: null };
  }
  if ('agent_id' in source) {
    const resolved = source.resolved?.display;
    const summary = source.manifest_summary;
    return normalizeDisplay(source.agent_id, resolved, summary);
  }
  const resolved = 'resolved_display' in source ? source.resolved_display : undefined;
  return normalizeDisplay(source.id, resolved, source);
}

export function resolvedAgentProfileLabel(agent: Agent | undefined, profiles: LlmProfile[], t?: TFunction): string {
  if (!agent) return '';
  const runtime = agent.resolved_runtime;
  const locked = runtime?.allow_session_override === false || agent.llm?.allow_session_override === false ? ` - ${t ? t('common:locked') : 'locked'}` : '';
  if (runtime?.llm_profile_label) return `${runtime.llm_profile_label}${locked}`;
  if (runtime?.llm_profile_status === 'missing' && runtime.llm_profile_id) return `${t ? t('chat:missingModelProfile') : 'Missing'}: ${runtime.llm_profile_id}${locked}`;
  if (runtime?.llm_profile_status === 'disabled' && runtime.llm_profile_id) return `${t ? t('common:disabled') : 'Disabled'}: ${runtime.llm_profile_id}${locked}`;
  if (runtime?.llm_profile_id) {
    const profile = profiles.find((item) => item.id === runtime.llm_profile_id || item.alias === runtime.llm_profile_id);
    return `${profile?.name || runtime.llm_profile_id}${locked}`;
  }
  if (agent.llm?.profile) {
    const profile = profiles.find((item) => item.id === agent.llm?.profile || item.alias === agent.llm?.profile);
    return `${profile?.name || agent.llm.profile}${locked}`;
  }
  const legacyModel =
    typeof agent.model?.model === 'string' ? agent.model.model : typeof agent.model?.model_id === 'string' ? agent.model.model_id : '';
  if (legacyModel) return `legacy: ${legacyModel}${locked}`;
  if (agent.type === 'prompt' || agent.capabilities?.includes('llm')) return `${t ? t('settings:llm.globalFallback') : 'uses global default'}${locked}`;
  return t ? t('chat:statusBar.llmNoLlm') : 'no llm';
}

function normalizeDisplay(id: string, resolved: ResolvedAgentDisplay | undefined, fallback: Partial<ResolvedAgentDisplayView>): ResolvedAgentDisplayView {
  return {
    id,
    name: resolved?.name || fallback.name || id,
    description: resolved?.description || fallback.description || '',
    avatar: resolved?.avatar ?? fallback.avatar ?? null,
    avatar_type: resolved?.avatar_type || fallback.avatar_type || 'initials',
    avatar_url: resolved?.avatar_url ?? fallback.avatar_url ?? null,
  };
}
