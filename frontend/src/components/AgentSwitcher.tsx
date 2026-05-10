import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, ChevronDown } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { AgentAvatar } from './AgentAvatar';
import { getResolvedAgentDisplay, resolvedAgentProfileLabel } from '../utils/agents';

export function AgentSwitcher() {
  const { t } = useTranslation();
  const { agents, currentSession, llmProfiles, updateDefaultAgent } = useWorkbenchStore();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const currentAgent = agents.find((agent) => agent.id === currentSession?.default_agent_id);
  const currentDisplay = getResolvedAgentDisplay(currentAgent);
  const currentSummary = resolvedAgentProfileLabel(currentAgent, llmProfiles);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false);
    }
    window.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  function selectAgent(agentId: string, enabled: boolean) {
    if (!enabled || !currentSession) return;
    setOpen(false);
    void updateDefaultAgent(agentId);
  }

  return (
    <div className="agent-switcher" ref={rootRef}>
      <button
        className="agent-switcher-button"
        type="button"
        onClick={() => setOpen((value) => !value)}
        disabled={!currentSession}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <AgentAvatar agent={currentDisplay} label={currentSession?.default_agent_id || 'AI'} className="agent-switcher-avatar" iconSize={14} />
        <span className="agent-switcher-copy">
          <strong>{currentAgent ? currentDisplay.name : currentSession?.default_agent_id || t('chat:noAgent')}</strong>
          {currentSummary ? <small>{currentSummary}</small> : null}
        </span>
        <ChevronDown size={15} className="agent-switcher-caret" />
      </button>
      {open ? (
        <div className="agent-menu" role="listbox">
          {agents.map((agent) => {
            const selected = agent.id === currentSession?.default_agent_id;
            const display = getResolvedAgentDisplay(agent);
            return (
              <button
                key={agent.id}
                className={`agent-menu-item ${selected ? 'selected' : ''}`}
                type="button"
                role="option"
                aria-selected={selected}
                disabled={!agent.enabled}
                onClick={() => selectAgent(agent.id, agent.enabled)}
              >
                <AgentAvatar agent={display} className="agent-menu-avatar" iconSize={14} />
                <span className="agent-menu-copy">
                  <strong>{display.name}</strong>
                  <small>{agent.enabled ? `${agent.id} - ${resolvedAgentProfileLabel(agent, llmProfiles, t)}` : `${agent.id} - ${t('chat:disabledSuffix')}`}</small>
                </span>
                {selected ? <Check size={15} /> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
