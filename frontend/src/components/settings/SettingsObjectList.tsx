import { Boxes, Plus, SlidersHorizontal } from 'lucide-react';
import type { AgentConfig, CapabilityConfig, EmbeddingModelProfile, KnowledgeBase, LlmProfile, LlmProviderProfile } from '../../types';
import { AgentAvatar } from '../AgentAvatar';
import { capabilitiesFromProfile, ModelCapabilityIcons } from '../ModelCapabilityIcons';
import type { KnowledgeSettingsSubsection, LlmSettingsSubsection, SettingsSection } from './SettingsNav';
import { initials } from './configUtils';
import { getResolvedAgentDisplay } from '../../utils/agents';

export type GeneralSettingsCategory = 'files' | 'llm_prompts';
export type KnowledgeSettingsCategory = KnowledgeSettingsSubsection;

const generalCategories: { id: GeneralSettingsCategory; name: string; description: string }[] = [
  { id: 'files', name: 'Files', description: 'Upload limits and file context.' },
  { id: 'llm_prompts', name: 'LLM & Prompts', description: 'Title generation and context prompts.' },
];

export function SettingsObjectList({
  section,
  llmSubsection = 'defaults',
  knowledgeSubsection = 'defaults',
  generalCategory = 'files',
  agentConfigs,
  capabilityConfigs,
  selectedAgentId,
  selectedCapabilityId,
  llmProfiles = [],
  llmProviderProfiles = [],
  selectedLlmItemId = 'global',
  embeddingProfiles = [],
  knowledgeBases = [],
  selectedKnowledgeItemId = 'global',
  onSelectGeneralCategory,
  onSelectAgent,
  onSelectCapability,
  onSelectLlmItem,
  onSelectKnowledgeItem,
}: {
  section: SettingsSection;
  llmSubsection?: LlmSettingsSubsection;
  knowledgeSubsection?: KnowledgeSettingsSubsection;
  generalCategory?: GeneralSettingsCategory;
  agentConfigs: AgentConfig[];
  capabilityConfigs: CapabilityConfig[];
  selectedAgentId?: string;
  selectedCapabilityId?: string;
  llmProfiles?: LlmProfile[];
  llmProviderProfiles?: LlmProviderProfile[];
  selectedLlmItemId?: string;
  embeddingProfiles?: EmbeddingModelProfile[];
  knowledgeBases?: KnowledgeBase[];
  selectedKnowledgeItemId?: string;
  onSelectGeneralCategory?: (category: GeneralSettingsCategory) => void;
  onSelectAgent: (agentId: string) => void;
  onSelectCapability: (capabilityId: string) => void;
  onSelectLlmItem?: (itemId: string) => void;
  onSelectKnowledgeItem?: (itemId: string) => void;
}) {
  if (section === 'general') {
    return (
      <aside className="settings-object-list" aria-label="General categories">
        <ObjectListHeader title="Category" count={generalCategories.length} />
        <div className="settings-list-scroll">
          {generalCategories.map((category) => (
            <button
              key={category.id}
              type="button"
              className={`settings-object-row ${generalCategory === category.id ? 'active' : ''}`}
              onClick={() => onSelectGeneralCategory?.(category.id)}
            >
              <div className="settings-object-avatar">
                <SlidersHorizontal size={16} />
              </div>
              <div className="settings-object-copy">
                <strong>{category.name}</strong>
                <small>{category.description}</small>
              </div>
            </button>
          ))}
        </div>
      </aside>
    );
  }

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

  if (section === 'knowledge') {
    if (knowledgeSubsection === 'defaults') {
      return (
        <aside className="settings-object-list" aria-label="Knowledge defaults">
          <ObjectListHeader title="DEFAULTS" count={1} />
          <button
            type="button"
            className={`settings-object-row ${selectedKnowledgeItemId === 'global' ? 'active' : ''}`}
            onClick={() => onSelectKnowledgeItem?.('global')}
          >
            <div className="settings-object-avatar">
              <SlidersHorizontal size={16} />
            </div>
            <div className="settings-object-copy">
              <strong>Knowledge defaults</strong>
              <small>Local model and retrieval defaults</small>
            </div>
          </button>
        </aside>
      );
    }

    if (knowledgeSubsection === 'embedding_models') {
      return (
        <aside className="settings-object-list" aria-label="Embedding model profiles">
          <ObjectListHeader title="EMBEDDING MODELS" count={embeddingProfiles.length} actionLabel="New model" onAction={() => onSelectKnowledgeItem?.('new')} />
          <div className="settings-list-scroll">
            {embeddingProfiles.length ? (
              embeddingProfiles.map((profile) => (
                <EmbeddingProfileListItem
                  key={profile.id}
                  profile={profile}
                  active={selectedKnowledgeItemId === profile.id}
                  onClick={() => onSelectKnowledgeItem?.(profile.id)}
                />
              ))
            ) : (
              <div className="settings-empty-state compact">No embedding model profiles yet.</div>
            )}
          </div>
        </aside>
      );
    }

    return (
      <aside className="settings-object-list" aria-label="Knowledge bases">
        <ObjectListHeader title="KNOWLEDGE BASES" count={knowledgeBases.length} actionLabel="New knowledge base" onAction={() => onSelectKnowledgeItem?.('new')} />
        <div className="settings-list-scroll">
          {knowledgeBases.length ? (
            knowledgeBases.map((knowledgeBase) => (
              <KnowledgeBaseListItem
                key={knowledgeBase.id}
                knowledgeBase={knowledgeBase}
                embeddingProfiles={embeddingProfiles}
                active={selectedKnowledgeItemId === knowledgeBase.id}
                onClick={() => onSelectKnowledgeItem?.(knowledgeBase.id)}
              />
            ))
          ) : (
            <div className="settings-empty-state compact">No knowledge bases yet.</div>
          )}
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
    if (llmSubsection === 'defaults') {
      return (
        <aside className="settings-object-list" aria-label="LLM defaults">
          <ObjectListHeader title="Defaults" count={1} />
          <button
            type="button"
            className={`settings-object-row ${selectedLlmItemId === 'global' ? 'active' : ''} ${llmEnabled ? '' : 'disabled'}`}
            onClick={() => onSelectLlmItem?.('global')}
          >
            <div className="settings-object-avatar">
              <SlidersHorizontal size={16} />
            </div>
            <div className="settings-object-copy">
              <strong>Default model profile</strong>
              <small>Global fallback</small>
            </div>
            <span className={`settings-status-dot ${llmEnabled ? 'enabled' : ''}`}>{llmEnabled ? 'Enabled' : 'Disabled'}</span>
          </button>
        </aside>
      );
    }
    if (llmSubsection === 'providers') {
      return (
        <aside className="settings-object-list" aria-label="LLM provider profiles">
          <ObjectListHeader title="Provider Profiles" count={llmProviderProfiles.length} actionLabel="New provider" onAction={() => onSelectLlmItem?.('new-provider')} />
          <div className="settings-list-scroll">
            {llmProviderProfiles.length ? (
              llmProviderProfiles.map((profile) => (
                <ProviderListItem
                  key={profile.id}
                  profile={profile}
                  active={selectedLlmItemId === `provider:${profile.id}`}
                  onClick={() => onSelectLlmItem?.(`provider:${profile.id}`)}
                />
              ))
            ) : (
              <div className="settings-empty-state compact">
                <p>No provider profiles yet.</p>
                <button className="settings-list-action" type="button" onClick={() => onSelectLlmItem?.('new-provider')}>
                  <Plus size={13} />
                  New provider
                </button>
              </div>
            )}
          </div>
        </aside>
      );
    }
    return (
      <aside className="settings-object-list" aria-label="LLM model profiles">
        <ObjectListHeader title="Model Profiles" count={llmProfiles.length} actionLabel="New model" onAction={() => onSelectLlmItem?.('new')} />
        <div className="settings-list-scroll llm-model-profile-list">
          {llmProfiles.length ? (
            llmProfiles.map((profile) => (
              <ProfileListItem
                key={profile.id}
                  profile={profile}
                  providerProfiles={llmProviderProfiles}
                  active={selectedLlmItemId === profile.id}
                onClick={() => onSelectLlmItem?.(profile.id)}
              />
            ))
          ) : (
            <div className="settings-empty-state compact">
              <p>No model profiles yet.</p>
              <button className="settings-list-action" type="button" onClick={() => onSelectLlmItem?.('new')}>
                <Plus size={13} />
                New model
              </button>
            </div>
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

function ProfileListItem({
  profile,
  providerProfiles,
  active,
  onClick,
}: {
  profile: LlmProfile;
  providerProfiles: LlmProviderProfile[];
  active: boolean;
  onClick: () => void;
}) {
  const providerName = providerProfiles.find((provider) => provider.id === profile.provider_profile_id)?.name || 'No provider';
  return (
    <button type="button" className={`settings-object-row llm-object-row llm-model-profile-row ${active ? 'active' : ''} ${profile.enabled ? '' : 'disabled'}`} onClick={onClick}>
      <div className="settings-object-avatar">{initials(profile.name) || <SlidersHorizontal size={16} />}</div>
      <div className="settings-object-copy">
        <div className="settings-object-title-row">
          <strong>{profile.name}</strong>
          <span className={`settings-status-dot ${profile.enabled ? 'enabled' : ''}`}>{profile.enabled ? 'Enabled' : 'Disabled'}</span>
        </div>
        <small>{providerName} / {profile.model_id || 'No model ID'}</small>
        <ModelCapabilityIcons capabilities={capabilitiesFromProfile(profile)} className="settings-capability-icons" />
      </div>
    </button>
  );
}

function ProviderListItem({ profile, active, onClick }: { profile: LlmProviderProfile; active: boolean; onClick: () => void }) {
  return (
    <button type="button" className={`settings-object-row llm-object-row ${active ? 'active' : ''} ${profile.enabled ? '' : 'disabled'}`} onClick={onClick}>
      <div className="settings-object-avatar">{initials(profile.name) || <SlidersHorizontal size={16} />}</div>
      <div className="settings-object-copy">
        <strong>{profile.name}</strong>
        <small>{profile.provider} / {profile.base_url || 'No base URL'}</small>
      </div>
      <span className={`settings-status-dot ${profile.enabled ? 'enabled' : ''}`}>{profile.enabled ? 'Enabled' : 'Disabled'}</span>
    </button>
  );
}

function EmbeddingProfileListItem({ profile, active, onClick }: { profile: EmbeddingModelProfile; active: boolean; onClick: () => void }) {
  return (
    <button type="button" className={`settings-object-row ${active ? 'active' : ''} ${profile.enabled ? '' : 'disabled'}`} onClick={onClick}>
      <div className="settings-object-avatar">{initials(profile.name) || <SlidersHorizontal size={16} />}</div>
      <div className="settings-object-copy">
        <strong>{profile.name || 'Untitled model'}</strong>
        <small>{profile.alias || 'No alias'} / {profile.model_path || 'No model path'}</small>
      </div>
      <span className={`settings-status-dot ${profile.enabled ? 'enabled' : ''}`}>{profile.enabled ? 'Enabled' : 'Disabled'}</span>
    </button>
  );
}

function KnowledgeBaseListItem({
  knowledgeBase,
  embeddingProfiles,
  active,
  onClick,
}: {
  knowledgeBase: KnowledgeBase;
  embeddingProfiles: EmbeddingModelProfile[];
  active: boolean;
  onClick: () => void;
}) {
  const profile = embeddingProfiles.find((item) => item.id === knowledgeBase.embedding_model_profile_id);
  return (
    <button type="button" className={`settings-object-row ${active ? 'active' : ''} ${knowledgeBase.enabled ? '' : 'disabled'}`} onClick={onClick}>
      <div className="settings-object-avatar">{initials(knowledgeBase.name) || <SlidersHorizontal size={16} />}</div>
      <div className="settings-object-copy">
        <strong>{knowledgeBase.name || 'Untitled knowledge base'}</strong>
        <small>{knowledgeBase.index_status || 'empty'} / {profile?.alias || 'missing model'}</small>
      </div>
      <span className={`settings-status-dot ${knowledgeBase.enabled ? 'enabled' : ''}`}>{knowledgeBase.enabled ? 'Enabled' : 'Disabled'}</span>
    </button>
  );
}

function AgentListItem({ config, active, onClick }: { config: AgentConfig; active: boolean; onClick: () => void }) {
  const display = getResolvedAgentDisplay(config);
  const label = display.name || config.agent_id;
  return (
    <button type="button" className={`settings-object-row ${active ? 'active' : ''} ${config.enabled ? '' : 'disabled'}`} onClick={onClick}>
      <AgentAvatar agent={display} label={label} className="settings-object-avatar" iconSize={16} />
      <div className="settings-object-copy">
        <strong>{label}</strong>
        <small>{display.description || config.agent_id}</small>
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
