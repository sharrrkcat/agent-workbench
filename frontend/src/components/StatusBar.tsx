import { Loader2 } from 'lucide-react';
import { resolveCurrentLlmProfile, useWorkbenchStore } from '../store/useWorkbenchStore';

export function StatusBar() {
  const state = useWorkbenchStore();
  const { loading, sending, savingConfigId, testingLlm, pendingActionKey, currentSession, health } = state;
  const resolvedProfile = resolveCurrentLlmProfile(state);
  const llmStatus = formatResolvedLlmStatus(state);
  const busy = loading || sending || Boolean(savingConfigId) || testingLlm || Boolean(pendingActionKey);

  return (
    <footer className="status-bar">
      <span className={health?.status === 'degraded' ? 'status-error' : 'status-item'}>
        Backend {health?.status || 'unknown'}
      </span>
      <span>{health?.version || 'version unknown'}</span>
      <span>{currentSession ? `Session ${currentSession.session_id.slice(0, 8)}` : 'No session'}</span>
      <span title={resolvedProfile?.model_id || ''}>{llmStatus}</span>
      {busy ? (
        <span className="status-item">
          <Loader2 size={14} className="spin" />
          {sending ? 'Sending' : testingLlm ? 'Testing LLM' : savingConfigId ? 'Saving' : pendingActionKey ? 'Running action' : 'Working'}
        </span>
      ) : null}
    </footer>
  );
}

function formatResolvedLlmStatus(state: ReturnType<typeof useWorkbenchStore.getState>): string {
  const agent = state.agents.find((item) => item.id === state.currentSession?.default_agent_id);
  if (agent && !agentUsesLlm(agent)) return 'LLM - No LLM';
  const profile = resolveCurrentLlmProfile(state);
  if (!profile) return 'LLM - No model profile selected';
  if (!profile.enabled) return 'LLM - Model disabled';
  const provider = profile.provider_profile_id ? state.llmProviderProfiles.find((item) => item.id === profile.provider_profile_id) : undefined;
  if (!provider) return 'LLM - Missing provider profile';
  return `LLM - ${provider.name} - ${profile.model_id || 'No model ID'}`;
}

function agentUsesLlm(agent: ReturnType<typeof useWorkbenchStore.getState>['agents'][number]): boolean {
  return agent.type === 'prompt' || Boolean(agent.llm) || agent.capabilities?.includes('llm') === true;
}
