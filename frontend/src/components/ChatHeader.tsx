import { Settings } from 'lucide-react';
import { AgentSwitcher } from './AgentSwitcher';
import { resolveCurrentLlmProfile, useWorkbenchStore } from '../store/useWorkbenchStore';
import { getModelProfileStatus, statusPillClass } from '../utils/modelStatus';

export function ChatHeader({ onOpenSettings }: { onOpenSettings: () => void }) {
  const currentSession = useWorkbenchStore((state) => state.currentSession);
  const state = useWorkbenchStore();
  const currentProfile = resolveCurrentLlmProfile(state);
  const modelStatus = getModelProfileStatus(currentProfile, state.llmProviderStatuses);

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
          className={`status-pill ${statusClass(modelStatus)}`}
          type="button"
          onClick={() => void state.refreshProviderStatuses()}
          title={statusTitle(modelStatus, currentProfile)}
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

function statusTitle(modelStatus: ReturnType<typeof getModelProfileStatus>, currentProfile: ReturnType<typeof resolveCurrentLlmProfile>): string {
  return [
    currentProfile?.name || currentProfile?.alias || 'Default',
    `Requested: ${currentProfile?.model_id || 'none'}`,
    `Status: ${modelStatus.label}`,
    modelStatus.title,
  ].filter(Boolean).join('\n');
}

function statusClass(modelStatus: ReturnType<typeof getModelProfileStatus>): string {
  return statusPillClass(modelStatus);
}
