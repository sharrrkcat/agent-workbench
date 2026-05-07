import { Settings } from 'lucide-react';
import { AgentSwitcher } from './AgentSwitcher';
import { resolveCurrentLlmProfile, useWorkbenchStore } from '../store/useWorkbenchStore';
import type { LlmProviderStatus } from '../types';

export function ChatHeader({ onOpenSettings }: { onOpenSettings: () => void }) {
  const currentSession = useWorkbenchStore((state) => state.currentSession);
  const state = useWorkbenchStore();
  const currentProfile = resolveCurrentLlmProfile(state);
  const providerStatus = currentProfile?.provider_profile_id ? state.llmProviderStatuses[currentProfile.provider_profile_id] : undefined;
  const modelStatus = statusForModel(providerStatus, currentProfile?.model_id || '');

  return (
    <header className="topbar">
      <div className="topbar-left">
        <AgentSwitcher />
        <span className="session-chip">
          {currentSession ? currentSession.title || `Session ${currentSession.session_id.slice(0, 6)}` : 'No session'}
        </span>
      </div>
      <div className="topbar-actions">
        <button
          className={`status-pill ${statusClass(modelStatus.code)}`}
          type="button"
          onClick={() => void state.refreshProviderStatuses()}
          title={statusTitle(providerStatus, currentProfile?.model_id || '')}
        >
          <span />
          {modelStatus.label}
        </button>
        <button className="tool-button" type="button" onClick={onOpenSettings} title="Open settings">
          <Settings size={17} />
          <span>Settings</span>
        </button>
      </div>
    </header>
  );
}

function statusForModel(providerStatus: LlmProviderStatus | undefined, modelId: string): { code: string; label: string } {
  if (!providerStatus) return { code: 'MODEL_STATUS_UNKNOWN', label: 'Unknown' };
  const model = providerStatus.models.find((item) => item.id === modelId);
  const code = model?.status || providerStatus.status || 'MODEL_STATUS_UNKNOWN';
  return { code, label: statusLabel(code) };
}

function statusLabel(code: string): string {
  if (code === 'READY') return 'Ready';
  if (code === 'PROVIDER_UNREACHABLE') return 'Unreachable';
  if (code === 'MODEL_NOT_AVAILABLE') return 'Model not available';
  if (code === 'MODEL_MISMATCH') return 'Mismatch';
  return 'Unknown';
}

function statusClass(code: string): string {
  if (code === 'READY') return 'ok';
  if (code === 'MODEL_MISMATCH') return 'warn';
  if (code === 'PROVIDER_UNREACHABLE' || code === 'MODEL_NOT_AVAILABLE') return 'error';
  return '';
}

function statusTitle(providerStatus: LlmProviderStatus | undefined, requestedModelId: string): string {
  if (!providerStatus) return 'Provider status unknown. Click to refresh all enabled provider profiles.';
  const warning = providerStatus.error?.message || providerStatus.warnings[0] || '';
  return [
    providerStatus.provider_profile_name,
    providerStatus.provider,
    `Requested: ${requestedModelId || 'none'}`,
    `Status: ${statusLabel(statusForModel(providerStatus, requestedModelId).code)}`,
    `Last checked: ${providerStatus.checked_at}`,
    warning,
  ].filter(Boolean).join('\n');
}
