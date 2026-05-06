import { Boxes, Plus, SlidersHorizontal } from 'lucide-react';
import type { AgentConfig, CapabilityConfig, LlmProfile } from '../../types';
import { AgentAvatar } from '../AgentAvatar';
import type { SettingsSection } from './SettingsNav';
import { initials } from './configUtils';

export function SettingsObjectList({
  section,
  agentConfigs,
  capabilityConfigs,
  selectedAgentId,
  selectedCapabilityId,
  llmProfiles = [],
  selectedLlmItemId = 'global',
  onSelectAgent,
  onSelectCapability,
  onSelectLlmItem,
}: {
  section: SettingsSection;
  agentConfigs: AgentConfig[];
  capabilityConfigs: CapabilityConfig[];
  selectedAgentId?: string;
  selectedCapabilityId?: string;
  llmProfiles?: LlmProfile[];
  selectedLlmItemId?: string;
  onSelectAgent: (agentId: string) => void;
  onSelectCapability: (capabilityId: string) => void;
  onSelectLlmItem?: (itemId: string) => void;
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
        <button
          type="button"
          className={`settings-object-row ${selectedLlmItemId === 'global' ? 'active' : ''} ${llmEnabled ? '' : 'disabled'}`}
          onClick={() => onSelectLlmItem?.('global')}
        >
          <div className="settings-object-avatar">
            <SlidersHorizontal size={16} />
          </div>
          <div className="settings-object-copy">
            <strong>Global fallback</strong>
            <small>LLM Capability</small>
          </div>
          <span className={`settings-status-dot ${llmEnabled ? 'enabled' : ''}`}>{llmEnabled ? 'Enabled' : 'Disabled'}</span>
        </button>
        <ObjectListHeader title="LLM Profiles" count={llmProfiles.length} actionLabel="New profile" onAction={() => onSelectLlmItem?.('new')} />
        <div className="settings-list-scroll">
          {llmProfiles.length ? (
            llmProfiles.map((profile) => (
              <ProfileListItem
                key={profile.id}
                profile={profile}
                active={selectedLlmItemId === profile.id}
                onClick={() => onSelectLlmItem?.(profile.id)}
              />
            ))
          ) : (
            <div className="settings-empty-state compact">No saved profiles.</div>
          )}
        </div>
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

function ObjectListHeader({ title, count, actionLabel, onAction }: { title: string; count: number; actionLabel?: string; onAction?: () => void }) {
  return (
    <div className="settings-list-header">
      <span>{title}</span>
      {actionLabel ? (
        <button className="settings-list-action" type="button" onClick={onAction}>
          <Plus size={13} />
          {actionLabel}
        </button>
      ) : (
        <small>{count}</small>
      )}
    </div>
  );
}

function ProfileListItem({ profile, active, onClick }: { profile: LlmProfile; active: boolean; onClick: () => void }) {
  return (
    <button type="button" className={`settings-object-row llm-object-row ${active ? 'active' : ''} ${profile.enabled ? '' : 'disabled'}`} onClick={onClick}>
      <div className="settings-object-avatar">{initials(profile.name) || <SlidersHorizontal size={16} />}</div>
      <div className="settings-object-copy">
        <strong>{profile.name}</strong>
        <small>{profile.provider} · {profile.model_id || 'No model ID'}</small>
        <CapabilityChips profile={profile} />
      </div>
      <span className={`settings-status-dot ${profile.enabled ? 'enabled' : ''}`}>{profile.enabled ? 'Enabled' : 'Disabled'}</span>
    </button>
  );
}

function CapabilityChips({ profile }: { profile: LlmProfile }) {
  const chips = [
    ['Vision', Boolean(profile.supports_vision)],
    ['Tools', Boolean(profile.supports_tools)],
    ['Reasoning', Boolean(profile.supports_reasoning)],
    ['Streaming', Boolean(profile.supports_streaming)],
    ['JSON', Boolean(profile.supports_json_mode)],
  ] as const;
  const enabled = chips.filter(([, value]) => value);
  if (!enabled.length) return null;
  return (
    <div className="settings-chip-row compact">
      {enabled.map(([label]) => <span key={label}>{label}</span>)}
    </div>
  );
}

function AgentListItem({ config, active, onClick }: { config: AgentConfig; active: boolean; onClick: () => void }) {
  const summary = config.manifest_summary;
  const label = summary.name || config.agent_id;
  return (
    <button type="button" className={`settings-object-row ${active ? 'active' : ''} ${config.enabled ? '' : 'disabled'}`} onClick={onClick}>
      <AgentAvatar agent={summary} label={label} className="settings-object-avatar" iconSize={16} />
      <div className="settings-object-copy">
        <strong>{label}</strong>
        <small>{config.agent_id}</small>
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
      </div>
      <span className={`settings-status-dot ${config.enabled ? 'enabled' : ''}`}>{config.enabled ? 'Enabled' : 'Disabled'}</span>
    </button>
  );
}
