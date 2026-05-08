import { Settings } from 'lucide-react';
import { AgentSwitcher } from './AgentSwitcher';
import { resolveCurrentLlmProfile, useWorkbenchStore } from '../store/useWorkbenchStore';
import { getModelProfileStatus, statusPillClass } from '../utils/modelStatus';
import type { ContextMode } from '../types';

export function ChatHeader({ onOpenSettings }: { onOpenSettings: () => void }) {
  const currentSession = useWorkbenchStore((state) => state.currentSession);
  const updateSessionContextMode = useWorkbenchStore((state) => state.updateSessionContextMode);
  const state = useWorkbenchStore();
  const currentProfile = resolveCurrentLlmProfile(state);
  const modelStatus = getModelProfileStatus(currentProfile, state.llmProviderStatuses);
  const contextMode = currentSession?.context_mode === 'group_transcript' ? 'group_transcript' : 'single_assistant';

  function changeContextMode(nextMode: ContextMode) {
    void updateSessionContextMode(nextMode);
  }

  return (
    <header className="topbar">
      <div className="topbar-left">
        <AgentSwitcher />
        <span className="session-chip">
          {currentSession ? currentSession.title || `Session ${currentSession.session_id.slice(0, 6)}` : 'No session'}
        </span>
      </div>
      <div className="topbar-actions">
        <div className="mode-switcher" aria-label="Conversation mode">
          <span>Mode</span>
          <button
            type="button"
            className={contextMode === 'single_assistant' ? 'selected' : ''}
            onClick={() => changeContextMode('single_assistant')}
            disabled={!currentSession}
            title="Single assistant: Treat agent history like a normal assistant conversation."
          >
            Single
          </button>
          <button
            type="button"
            className={contextMode === 'group_transcript' ? 'selected' : ''}
            onClick={() => changeContextMode('group_transcript')}
            disabled={!currentSession}
            title="Group transcript: Label user, agents, and command results in context so agents can distinguish speakers."
          >
            Group
          </button>
        </div>
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
