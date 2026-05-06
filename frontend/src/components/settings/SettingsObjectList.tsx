import { Bot, Boxes, SlidersHorizontal } from 'lucide-react';
import type { AgentConfig, CapabilityConfig } from '../../types';
import type { SettingsSection } from './SettingsNav';
import { initials } from './configUtils';

export function SettingsObjectList({
  section,
  agentConfigs,
  capabilityConfigs,
  selectedAgentId,
  selectedCapabilityId,
  onSelectAgent,
  onSelectCapability,
}: {
  section: SettingsSection;
  agentConfigs: AgentConfig[];
  capabilityConfigs: CapabilityConfig[];
  selectedAgentId?: string;
  selectedCapabilityId?: string;
  onSelectAgent: (agentId: string) => void;
  onSelectCapability: (capabilityId: string) => void;
}) {
  if (section === 'agents') {
    return (
      <aside className="settings-object-list" aria-label="Agents">
        <ObjectListHeader title="Agents" count={agentConfigs.length} />
        <div className="settings-list-scroll">
          {agentConfigs.map((config) => (
            <AgentListItem
              key={config.agent_id}
              config={config}
              active={selectedAgentId === config.agent_id}
              onClick={() => onSelectAgent(config.agent_id)}
            />
          ))}
        </div>
      </aside>
    );
  }

  if (section === 'capabilities') {
    return (
      <aside className="settings-object-list" aria-label="Capabilities">
        <ObjectListHeader title="Capabilities" count={capabilityConfigs.length} />
        <div className="settings-list-scroll">
          {capabilityConfigs.map((config) => (
            <CapabilityListItem
              key={config.capability_id}
              config={config}
              active={selectedCapabilityId === config.capability_id}
              onClick={() => onSelectCapability(config.capability_id)}
            />
          ))}
        </div>
      </aside>
    );
  }

  if (section === 'llm') {
    const llmConfig = capabilityConfigs.find((config) => config.capability_id === 'llm');
    const llmEnabled = llmConfig?.enabled ?? false;
    return (
      <aside className="settings-object-list" aria-label="LLM settings">
        <ObjectListHeader title="LLM" count={1} />
        <button type="button" className={`settings-object-row active ${llmEnabled ? '' : 'disabled'}`}>
          <div className="settings-object-avatar">
            <SlidersHorizontal size={16} />
          </div>
          <div className="settings-object-copy">
            <strong>{llmConfig?.manifest_summary.name || 'LLM Runtime'}</strong>
            <small>{llmConfig?.capability_id || 'llm'}</small>
            <p>{llmConfig?.manifest_summary.description || 'OpenAI-compatible local model connection.'}</p>
          </div>
          <span className={`settings-status-dot ${llmEnabled ? 'enabled' : ''}`}>{llmEnabled ? 'Enabled' : 'Disabled'}</span>
        </button>
      </aside>
    );
  }

  return (
    <aside className="settings-object-list" aria-label="Settings category">
      <ObjectListHeader title="Category" count={0} />
      <div className="settings-empty-state compact">No objects in this section.</div>
    </aside>
  );
}

function ObjectListHeader({ title, count }: { title: string; count: number }) {
  return (
    <div className="settings-list-header">
      <span>{title}</span>
      <small>{count}</small>
    </div>
  );
}

function AgentListItem({ config, active, onClick }: { config: AgentConfig; active: boolean; onClick: () => void }) {
  const summary = config.manifest_summary;
  const label = summary.name || config.agent_id;
  const avatar = summary.avatar?.trim();
  return (
    <button type="button" className={`settings-object-row ${active ? 'active' : ''} ${config.enabled ? '' : 'disabled'}`} onClick={onClick}>
      <div className="settings-object-avatar">{avatar || initials(label) || <Bot size={16} />}</div>
      <div className="settings-object-copy">
        <strong>{label}</strong>
        <small>{config.agent_id}</small>
        <p>{summary.description || 'No description.'}</p>
      </div>
      <span className={`settings-status-dot ${config.enabled ? 'enabled' : ''}`}>{config.enabled ? 'Enabled' : 'Disabled'}</span>
    </button>
  );
}

function CapabilityListItem({
  config,
  active,
  onClick,
}: {
  config: CapabilityConfig;
  active: boolean;
  onClick: () => void;
}) {
  const summary = config.manifest_summary;
  const label = summary.name || config.capability_id;
  return (
    <button type="button" className={`settings-object-row ${active ? 'active' : ''} ${config.enabled ? '' : 'disabled'}`} onClick={onClick}>
      <div className="settings-object-avatar">{initials(label) || <Boxes size={16} />}</div>
      <div className="settings-object-copy">
        <strong>{label}</strong>
        <small>{config.capability_id}</small>
        <p>{summary.description || 'No description.'}</p>
      </div>
      <span className={`settings-status-dot ${config.enabled ? 'enabled' : ''}`}>{config.enabled ? 'Enabled' : 'Disabled'}</span>
    </button>
  );
}
