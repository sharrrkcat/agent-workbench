import { BookOpen, Settings } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { AgentSwitcher } from './AgentSwitcher';
import { resolveCurrentLlmProfile, useWorkbenchStore } from '../store/useWorkbenchStore';
import { getModelProfileStatus, statusPillClass } from '../utils/modelStatus';
import type { ContextMode, KnowledgeBase, SessionKnowledgeBinding } from '../types';

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
        <SessionKnowledgePicker onOpenSettings={onOpenSettings} />
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

function SessionKnowledgePicker({ onOpenSettings }: { onOpenSettings: () => void }) {
  const currentSession = useWorkbenchStore((state) => state.currentSession);
  const [open, setOpen] = useState(false);
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [bindings, setBindings] = useState<SessionKnowledgeBinding[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const selectedIds = useMemo(() => new Set(bindings.filter((binding) => binding.enabled).map((binding) => binding.knowledge_base_id)), [bindings]);
  const enabledBases = bases.filter((base) => base.enabled);

  useEffect(() => {
    if (!currentSession?.session_id) {
      setBases([]);
      setBindings([]);
      return;
    }
    let cancelled = false;
    async function load() {
      try {
        setError('');
        const [nextBases, nextBindings] = await Promise.all([
          api.listKnowledgeBases(),
          api.listSessionKnowledgeBases(currentSession!.session_id),
        ]);
        if (cancelled) return;
        setBases(nextBases);
        setBindings(nextBindings);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load knowledge bases.');
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [currentSession?.session_id]);

  async function toggleBase(baseId: string) {
    if (!currentSession || busy) return;
    const nextIds = selectedIds.has(baseId)
      ? [...selectedIds].filter((id) => id !== baseId)
      : [...selectedIds, baseId];
    setBusy(true);
    try {
      const nextBindings = await api.updateSessionKnowledgeBases(currentSession.session_id, nextIds);
      setBindings(nextBindings);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save knowledge bases.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="knowledge-picker">
      <button
        type="button"
        className="status-pill"
        disabled={!currentSession}
        onClick={() => setOpen(!open)}
        title="Select session knowledge bases"
      >
        <BookOpen size={14} />
        KB: {selectedIds.size}
      </button>
      {open ? (
        <div className="knowledge-picker-menu">
          <div className="knowledge-picker-title">
            <strong>Knowledge</strong>
            <span>{selectedIds.size} selected</span>
          </div>
          {error ? <p className="settings-error-text">{error}</p> : null}
          {!bases.length ? (
            <div className="settings-empty-state compact">
              No knowledge bases yet. Open Settings &gt; Knowledge to create one.
              <button type="button" className="settings-secondary-button" onClick={onOpenSettings}>Open settings</button>
            </div>
          ) : null}
          {bases.length && !enabledBases.length ? <div className="settings-empty-state compact">All knowledge bases are disabled.</div> : null}
          <div className="knowledge-picker-list">
            {bases.map((base) => (
              <label key={base.id} className={`knowledge-picker-row ${base.enabled ? '' : 'disabled'}`}>
                <input
                  type="checkbox"
                  checked={selectedIds.has(base.id)}
                  disabled={!base.enabled || busy}
                  onChange={() => void toggleBase(base.id)}
                />
                <span>
                  <strong>{base.name}</strong>
                  <small>{base.enabled ? base.index_status : 'disabled'}</small>
                </span>
              </label>
            ))}
          </div>
        </div>
      ) : null}
    </div>
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
