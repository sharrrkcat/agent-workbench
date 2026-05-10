import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { resolveCurrentLlmProfile, useWorkbenchStore } from '../store/useWorkbenchStore';

export function StatusBar() {
  const { t } = useTranslation();
  const state = useWorkbenchStore();
  const { loading, sending, savingConfigId, testingLlm, pendingActionKey, currentSession, health } = state;
  const resolvedProfile = resolveCurrentLlmProfile(state);
  const llmStatus = formatResolvedLlmStatus(state, t);
  const busy = loading || sending || Boolean(savingConfigId) || testingLlm || Boolean(pendingActionKey);

  return (
    <footer className="status-bar">
      <span className={health?.status === 'degraded' ? 'status-error' : 'status-item'}>
        {t('chat:statusBar.backend', { status: health?.status || t('status:common.unknown') })}
      </span>
      <span>{health?.version || t('chat:statusBar.versionUnknown')}</span>
      <span>{currentSession ? t('chat:statusBar.session', { id: currentSession.session_id.slice(0, 8) }) : t('common:noSession')}</span>
      <span title={resolvedProfile?.model_id || ''}>{llmStatus}</span>
      {busy ? (
        <span className="status-item">
          <Loader2 size={14} className="spin" />
          {sending ? t('chat:status.sending') : testingLlm ? t('chat:status.testingLlm') : savingConfigId ? t('chat:status.saving') : pendingActionKey ? t('chat:status.runningAction') : t('common:working')}
        </span>
      ) : null}
    </footer>
  );
}

function formatResolvedLlmStatus(state: ReturnType<typeof useWorkbenchStore.getState>, t: ReturnType<typeof useTranslation>['t']): string {
  const agent = state.agents.find((item) => item.id === state.currentSession?.default_agent_id);
  if (agent && !agentUsesLlm(agent)) return t('chat:statusBar.llmNoLlm');
  const profile = resolveCurrentLlmProfile(state);
  if (!profile) return t('chat:statusBar.llmNoModelProfile');
  if (!profile.enabled) return t('chat:statusBar.llmModelDisabled');
  const provider = profile.provider_profile_id ? state.llmProviderProfiles.find((item) => item.id === profile.provider_profile_id) : undefined;
  if (!provider) return t('chat:statusBar.llmMissingProviderProfile');
  return t('chat:statusBar.llmProviderModel', { provider: provider.name, model: profile.model_id || t('chat:statusBar.llmNoModelId') });
}

function agentUsesLlm(agent: ReturnType<typeof useWorkbenchStore.getState>['agents'][number]): boolean {
  return agent.type === 'prompt' || Boolean(agent.llm) || agent.capabilities?.includes('llm') === true;
}
