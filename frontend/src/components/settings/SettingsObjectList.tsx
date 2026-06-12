import { Activity, Boxes, Gauge, Globe, PawPrint, Plus, SlidersHorizontal, Type } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { AgentConfig, CapabilityConfig, EmbeddingModelProfile, KnowledgeBase, LlmProfile, LlmProviderProfile, MultimodalEmbeddingModelProfile, RerankerModelProfile, VisionModelProfile, Worldbook } from '../../types';
import { AgentAvatar } from '../AgentAvatar';
import { capabilitiesFromProfile, ModelCapabilityIcons } from '../ModelCapabilityIcons';
import type { KnowledgeSettingsSubsection, LlmSettingsSubsection, SettingsSection, WorldbookSettingsSubsection } from './SettingsNav';
import { initials } from './configUtils';
import { getResolvedAgentDisplay } from '../../utils/agents';
import { StatusChip } from '../ui';
import { getKnowledgeIndexStatusLabel } from '../../i18n/formatters';

export type GeneralSettingsCategory = 'files' | 'llm_prompts' | 'memory' | 'web_search' | 'utility_llm' | 'intent_routing' | 'inference_service';
export type AppearanceSettingsCategory = 'pet' | 'fonts' | 'chat_status_panel';
export type KnowledgeSettingsCategory = KnowledgeSettingsSubsection | 'reranker_models';
export type WorldbookSettingsCategory = WorldbookSettingsSubsection;

export function SettingsObjectList({
  section,
  llmSubsection = 'providers',
  knowledgeSubsection = 'defaults',
  worldbookSubsection = 'defaults',
  generalCategory = 'files',
  appearanceCategory = 'pet',
  agentConfigs,
  capabilityConfigs,
  selectedAgentId,
  selectedCapabilityId,
  llmProfiles = [],
  llmProviderProfiles = [],
  selectedLlmItemId = 'global',
  embeddingProfiles = [],
  multimodalEmbeddingProfiles = [],
  selectedMultimodalEmbeddingItemId = '',
  visionProfiles = [],
  selectedVisionItemId = '',
  rerankerProfiles = [],
  knowledgeBases = [],
  selectedKnowledgeItemId = 'global',
  worldbooks = [],
  selectedWorldbookItemId = 'global',
  onSelectGeneralCategory,
  onSelectAppearanceCategory,
  onSelectAgent,
  onSelectCapability,
  onSelectLlmItem,
  onSelectMultimodalEmbeddingItem,
  onSelectVisionItem,
  onSelectKnowledgeItem,
  onSelectWorldbookItem,
}: {
  section: SettingsSection;
  llmSubsection?: LlmSettingsSubsection;
  knowledgeSubsection?: KnowledgeSettingsSubsection;
  worldbookSubsection?: WorldbookSettingsSubsection;
  generalCategory?: GeneralSettingsCategory;
  appearanceCategory?: AppearanceSettingsCategory;
  agentConfigs: AgentConfig[];
  capabilityConfigs: CapabilityConfig[];
  selectedAgentId?: string;
  selectedCapabilityId?: string;
  llmProfiles?: LlmProfile[];
  llmProviderProfiles?: LlmProviderProfile[];
  selectedLlmItemId?: string;
  embeddingProfiles?: EmbeddingModelProfile[];
  multimodalEmbeddingProfiles?: MultimodalEmbeddingModelProfile[];
  selectedMultimodalEmbeddingItemId?: string;
  visionProfiles?: VisionModelProfile[];
  selectedVisionItemId?: string;
  rerankerProfiles?: RerankerModelProfile[];
  knowledgeBases?: KnowledgeBase[];
  selectedKnowledgeItemId?: string;
  worldbooks?: Worldbook[];
  selectedWorldbookItemId?: string;
  onSelectGeneralCategory?: (category: GeneralSettingsCategory) => void;
  onSelectAppearanceCategory?: (category: AppearanceSettingsCategory) => void;
  onSelectAgent: (agentId: string) => void;
  onSelectCapability: (capabilityId: string) => void;
  onSelectLlmItem?: (itemId: string) => void;
  onSelectMultimodalEmbeddingItem?: (itemId: string) => void;
  onSelectVisionItem?: (itemId: string) => void;
  onSelectKnowledgeItem?: (itemId: string) => void;
  onSelectWorldbookItem?: (itemId: string) => void;
}) {
  const { t } = useTranslation(['settings', 'common', 'status']);
  const generalCategories: { id: GeneralSettingsCategory; name: string; description: string; icon: typeof SlidersHorizontal }[] = [
    { id: 'files', name: t('settings:general.files'), description: t('settings:general.filesDescription'), icon: SlidersHorizontal },
    { id: 'llm_prompts', name: t('settings:general.llmPrompts'), description: t('settings:general.llmPromptsDescription'), icon: SlidersHorizontal },
    { id: 'memory', name: t('settings:general.memory'), description: t('settings:general.memoryDescription'), icon: SlidersHorizontal },
    { id: 'web_search', name: t('settings:general.webSearch'), description: t('settings:general.webSearchDescription'), icon: Globe },
    { id: 'utility_llm', name: t('settings:general.utilityLlm'), description: t('settings:general.utilityLlmDescription'), icon: SlidersHorizontal },
    { id: 'intent_routing', name: t('settings:general.intentRouting'), description: t('settings:general.intentRoutingDescription'), icon: SlidersHorizontal },
    { id: 'inference_service', name: t('settings:general.inferenceService'), description: t('settings:general.inferenceServiceDescription'), icon: Activity },
  ];
  const appearanceCategories: { id: AppearanceSettingsCategory; name: string; description: string; icon: typeof PawPrint }[] = [
    { id: 'pet', name: t('settings:appearance.pet'), description: t('settings:appearance.petDescription'), icon: PawPrint },
    { id: 'fonts', name: t('settings:appearance.fonts'), description: t('settings:appearance.fontsDescription'), icon: Type },
    { id: 'chat_status_panel', name: t('settings:appearance.chatStatusPanel'), description: t('settings:appearance.chatStatusPanelDescription'), icon: Gauge },
  ];

  if (section === 'general') {
    return (
      <aside className="settings-object-list" aria-label={t('settings:objectList.generalCategories')}>
        <ObjectListHeader title={t('settings:objectList.category')} count={generalCategories.length} />
        <div className="settings-list-scroll">
          {generalCategories.map((category) => {
            const Icon = category.icon;
            return (
              <button
                key={category.id}
                type="button"
                className={`settings-object-row ${generalCategory === category.id ? 'active' : ''}`}
                onClick={() => onSelectGeneralCategory?.(category.id)}
              >
                <div className="settings-object-avatar">
                  <Icon size={16} />
                </div>
                <div className="settings-object-copy">
                  <strong>{category.name}</strong>
                  <small>{category.description}</small>
                </div>
              </button>
            );
          })}
        </div>
      </aside>
    );
  }

  if (section === 'agents') {
    return (
      <aside className="settings-object-list" aria-label={t('settings:objectList.agents')}>
        <ObjectListHeader title={t('settings:objectList.agents')} count={agentConfigs.length} />
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

  if (section === 'appearance') {
    return (
      <aside className="settings-object-list" aria-label={t('settings:objectList.appearanceItems')}>
        <ObjectListHeader title={t('settings:objectList.appearance')} count={appearanceCategories.length} />
        <div className="settings-list-scroll">
          {appearanceCategories.map((category) => {
            const Icon = category.icon;
            return (
              <button
                key={category.id}
                type="button"
                className={`settings-object-row ${appearanceCategory === category.id ? 'active' : ''}`}
                onClick={() => onSelectAppearanceCategory?.(category.id)}
              >
                <div className="settings-object-avatar">
                  <Icon size={16} />
                </div>
                <div className="settings-object-copy">
                  <strong>{category.name}</strong>
                  <small>{category.description}</small>
                </div>
              </button>
            );
          })}
        </div>
      </aside>
    );
  }

  if (section === 'knowledge') {
    if (knowledgeSubsection === 'defaults') {
      return (
        <aside className="settings-object-list" aria-label={t('settings:objectList.knowledgeDefaults')}>
          <ObjectListHeader title={t('settings:subsections.defaults')} count={1} />
          <button
            type="button"
            className={`settings-object-row ${selectedKnowledgeItemId === 'global' ? 'active' : ''}`}
            onClick={() => onSelectKnowledgeItem?.('global')}
          >
            <div className="settings-object-avatar">
              <SlidersHorizontal size={16} />
            </div>
            <div className="settings-object-copy">
              <strong>{t('settings:knowledge.defaultsName')}</strong>
              <small>{t('settings:knowledge.defaultsDescription')}</small>
            </div>
          </button>
        </aside>
      );
    }

    if (knowledgeSubsection === 'embedding_models') {
      return (
        <aside className="settings-object-list" aria-label={t('settings:objectList.embeddingModelProfiles')}>
          <ObjectListHeader title={t('settings:subsections.embeddingModels')} count={embeddingProfiles.length} actionLabel={t('settings:objectList.newModel')} onAction={() => onSelectKnowledgeItem?.('new')} />
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
              <div className="settings-empty-state compact">{t('settings:objectList.noEmbeddingProfiles')}</div>
            )}
          </div>
        </aside>
      );
    }

    return (
      <aside className="settings-object-list" aria-label={t('settings:objectList.knowledgeBases')}>
        <ObjectListHeader title={t('settings:subsections.knowledgeBases')} count={knowledgeBases.length} actionLabel={t('settings:objectList.newKnowledgeBase')} onAction={() => onSelectKnowledgeItem?.('new')} />
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
            <div className="settings-empty-state compact">{t('settings:objectList.noKnowledgeBases')}</div>
          )}
        </div>
      </aside>
    );
  }

  if (section === 'worldbook') {
    if (worldbookSubsection === 'defaults') {
      return (
        <aside className="settings-object-list" aria-label={t('settings:objectList.worldbookDefaults')}>
          <ObjectListHeader title={t('settings:subsections.defaults')} count={1} />
          <button
            type="button"
            className={`settings-object-row ${selectedWorldbookItemId === 'global' ? 'active' : ''}`}
            onClick={() => onSelectWorldbookItem?.('global')}
          >
            <div className="settings-object-avatar">
              <SlidersHorizontal size={16} />
            </div>
            <div className="settings-object-copy">
              <strong>{t('settings:worldbook.defaultsName')}</strong>
              <small>{t('settings:worldbook.defaultsDescription')}</small>
            </div>
          </button>
        </aside>
      );
    }
    return (
      <aside className="settings-object-list" aria-label={t('settings:objectList.worldbooks')}>
        <ObjectListHeader title={t('settings:subsections.worldbooks')} count={worldbooks.length} actionLabel={t('settings:objectList.newWorldbook')} onAction={() => onSelectWorldbookItem?.('new')} />
        <div className="settings-list-scroll">
          {worldbooks.length ? (
            worldbooks.map((worldbook) => (
              <button key={worldbook.id} type="button" className={`settings-object-row ${selectedWorldbookItemId === worldbook.id ? 'active' : ''} ${worldbook.enabled ? '' : 'disabled'}`} onClick={() => onSelectWorldbookItem?.(worldbook.id)}>
                <div className="settings-object-avatar">{initials(worldbook.name) || <SlidersHorizontal size={16} />}</div>
                <div className="settings-object-copy">
                  <strong>{worldbook.name || t('settings:worldbook.untitledWorldbook')}</strong>
                  <small>{t('settings:worldbook.entryCount', { count: worldbook.entry_count || 0 })}</small>
                </div>
                <span className={`settings-status-dot ${worldbook.enabled ? 'enabled' : ''}`}>{worldbook.enabled ? t('common:enabled') : t('common:disabled')}</span>
              </button>
            ))
          ) : (
            <div className="settings-empty-state compact">{t('settings:objectList.noWorldbooks')}</div>
          )}
        </div>
      </aside>
    );
  }

  if (section === 'capabilities') {
    return (
      <aside className="settings-object-list" aria-label={t('settings:objectList.capabilities')}>
        <ObjectListHeader title={t('settings:objectList.capabilities')} count={capabilityConfigs.length} />
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

  if (section === 'models') {
    if (llmSubsection === 'reranker_models') {
      return (
        <aside className="settings-object-list" aria-label={t('settings:objectList.rerankerModelProfiles')}>
          <ObjectListHeader title={t('settings:subsections.rerankerModels')} count={rerankerProfiles.length} actionLabel={t('settings:objectList.newModel')} onAction={() => onSelectKnowledgeItem?.('new')} />
          <div className="settings-list-scroll">
            {rerankerProfiles.length ? (
              rerankerProfiles.map((profile) => (
                <RerankerProfileListItem
                  key={profile.id}
                  profile={profile}
                  active={selectedKnowledgeItemId === profile.id}
                  onClick={() => onSelectKnowledgeItem?.(profile.id)}
                />
              ))
            ) : (
              <div className="settings-empty-state compact">{t('settings:objectList.noRerankerProfiles')}</div>
            )}
          </div>
        </aside>
      );
    }
    if (llmSubsection === 'embedding_models') {
      return (
        <aside className="settings-object-list" aria-label={t('settings:objectList.embeddingModelProfiles')}>
          <ObjectListHeader title={t('settings:subsections.embeddingModels')} count={embeddingProfiles.length} actionLabel={t('settings:objectList.newModel')} onAction={() => onSelectKnowledgeItem?.('new')} />
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
              <div className="settings-empty-state compact">{t('settings:objectList.noEmbeddingProfiles')}</div>
            )}
          </div>
        </aside>
      );
    }
    if (llmSubsection === 'multimodal_embedding_models') {
      return (
        <aside className="settings-object-list" aria-label={t('settings:objectList.multimodalEmbeddingModelProfiles')}>
          <ObjectListHeader title={t('settings:subsections.multimodalEmbeddingModels')} count={multimodalEmbeddingProfiles.length} actionLabel={t('settings:objectList.newModel')} onAction={() => onSelectMultimodalEmbeddingItem?.('new')} />
          <div className="settings-list-scroll">
            {multimodalEmbeddingProfiles.length ? (
              multimodalEmbeddingProfiles.map((profile) => (
                <MultimodalEmbeddingProfileListItem
                  key={profile.id}
                  profile={profile}
                  active={selectedMultimodalEmbeddingItemId === profile.id}
                  onClick={() => onSelectMultimodalEmbeddingItem?.(profile.id)}
                />
              ))
            ) : (
              <div className="settings-empty-state compact">{t('settings:objectList.noMultimodalEmbeddingProfiles')}</div>
            )}
          </div>
        </aside>
      );
    }
    if (llmSubsection === 'vision_models') {
      return (
        <aside className="settings-object-list" aria-label={t('settings:objectList.visionModelProfiles')}>
          <ObjectListHeader title={t('settings:subsections.visionModels')} count={visionProfiles.length} actionLabel={t('settings:objectList.newModel')} onAction={() => onSelectVisionItem?.('new')} />
          <div className="settings-list-scroll">
            {visionProfiles.length ? (
              visionProfiles.map((profile) => (
                <VisionProfileListItem
                  key={profile.id}
                  profile={profile}
                  active={selectedVisionItemId === profile.id}
                  onClick={() => onSelectVisionItem?.(profile.id)}
                />
              ))
            ) : (
              <div className="settings-empty-state compact">{t('settings:objectList.noVisionProfiles')}</div>
            )}
          </div>
        </aside>
      );
    }
    if (llmSubsection === 'providers') {
      return (
        <aside className="settings-object-list" aria-label={t('settings:objectList.llmProviderProfiles')}>
          <ObjectListHeader title={t('settings:subsections.providerProfiles')} count={llmProviderProfiles.length} actionLabel={t('settings:objectList.newProvider')} onAction={() => onSelectLlmItem?.('new-provider')} />
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
                <p>{t('settings:objectList.noProviderProfiles')}</p>
                <button className="settings-list-action" type="button" onClick={() => onSelectLlmItem?.('new-provider')}>
                  <Plus size={13} />
                  {t('settings:objectList.newProvider')}
                </button>
              </div>
            )}
          </div>
        </aside>
      );
    }
    return (
      <aside className="settings-object-list" aria-label={t('settings:objectList.llmModelProfiles')}>
        <ObjectListHeader title={t('settings:subsections.modelProfiles')} count={llmProfiles.length} actionLabel={t('settings:objectList.newModel')} onAction={() => onSelectLlmItem?.('new')} />
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
              <p>{t('settings:objectList.noModelProfiles')}</p>
              <button className="settings-list-action" type="button" onClick={() => onSelectLlmItem?.('new')}>
                <Plus size={13} />
                {t('settings:objectList.newModel')}
              </button>
            </div>
          )}
        </div>
      </aside>
    );
  }

  return (
    <aside className="settings-object-list" aria-label={t('settings:objectList.settingsCategory')}>
      <ObjectListHeader title={t('settings:objectList.category')} count={0} />
      <div className="settings-empty-state compact">{t('settings:objectList.noObjects')}</div>
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
  const { t } = useTranslation(['common', 'settings']);
  const providerName = providerProfiles.find((provider) => provider.id === profile.provider_profile_id)?.name || t('settings:objectList.noProviderProfile');
  return (
    <button type="button" className={`settings-object-row llm-object-row llm-model-profile-row ${active ? 'active' : ''} ${profile.enabled ? '' : 'disabled'}`} onClick={onClick}>
      <div className="settings-object-avatar">{initials(profile.name) || <SlidersHorizontal size={16} />}</div>
      <div className="settings-object-copy">
        <div className="settings-object-title-row">
          <strong>{profile.name}</strong>
          <span className={`settings-status-dot ${profile.enabled ? 'enabled' : ''}`}>{profile.enabled ? t('enabled') : t('disabled')}</span>
        </div>
        <small>{providerName} / {profile.model_id || t('settings:objectList.noModelRef')}</small>
        <ModelCapabilityIcons capabilities={capabilitiesFromProfile(profile)} className="settings-capability-icons" />
      </div>
    </button>
  );
}

function ProviderListItem({ profile, active, onClick }: { profile: LlmProviderProfile; active: boolean; onClick: () => void }) {
  const { t } = useTranslation('common');
  return (
    <button type="button" className={`settings-object-row llm-object-row ${active ? 'active' : ''} ${profile.enabled ? '' : 'disabled'}`} onClick={onClick}>
      <div className="settings-object-avatar">{initials(profile.name) || <SlidersHorizontal size={16} />}</div>
      <div className="settings-object-copy">
        <strong>{profile.name}</strong>
        <small>{profile.provider} / {profile.base_url || 'No base URL'}</small>
      </div>
      <span className={`settings-status-dot ${profile.enabled ? 'enabled' : ''}`}>{profile.enabled ? t('enabled') : t('disabled')}</span>
    </button>
  );
}

function EmbeddingProfileListItem({ profile, active, onClick }: { profile: EmbeddingModelProfile; active: boolean; onClick: () => void }) {
  const { t } = useTranslation(['common', 'settings', 'knowledge']);
  const modelLabel = profile.provider_model_id || (profile.model_path ? t('knowledge:labels.legacyModelPathValue', { path: profile.model_path }) : t('settings:objectList.noModelRef'));
  return (
    <button type="button" className={`settings-object-row ${active ? 'active' : ''} ${profile.enabled ? '' : 'disabled'}`} onClick={onClick}>
      <div className="settings-object-avatar">{initials(profile.name) || <SlidersHorizontal size={16} />}</div>
      <div className="settings-object-copy">
        <strong>{profile.name || t('settings:objectList.untitledModel')}</strong>
        <small>{profile.alias || t('settings:objectList.noProfileKey')} / {modelLabel}</small>
      </div>
      <span className={`settings-status-dot ${profile.enabled ? 'enabled' : ''}`}>{profile.enabled ? t('enabled') : t('disabled')}</span>
    </button>
  );
}

function RerankerProfileListItem({ profile, active, onClick }: { profile: RerankerModelProfile; active: boolean; onClick: () => void }) {
  const { t } = useTranslation(['common', 'settings']);
  return (
    <button type="button" className={`settings-object-row ${active ? 'active' : ''} ${profile.enabled ? '' : 'disabled'}`} onClick={onClick}>
      <div className="settings-object-avatar">{initials(profile.name) || <SlidersHorizontal size={16} />}</div>
      <div className="settings-object-copy">
        <strong>{profile.name || t('settings:objectList.untitledModel')}</strong>
        <small>{profile.alias || t('settings:objectList.noProfileKey')} / {profile.provider_model_id || t('settings:objectList.noModelRef')}</small>
      </div>
      <span className={`settings-status-dot ${profile.enabled ? 'enabled' : ''}`}>{profile.enabled ? t('enabled') : t('disabled')}</span>
    </button>
  );
}

function MultimodalEmbeddingProfileListItem({ profile, active, onClick }: { profile: MultimodalEmbeddingModelProfile; active: boolean; onClick: () => void }) {
  const { t } = useTranslation(['common', 'settings']);
  const architecture = t(`settings:multimodal.architectures.${profile.architecture}`, { defaultValue: profile.architecture });
  return (
    <button type="button" className={`settings-object-row ${active ? 'active' : ''} ${profile.enabled ? '' : 'disabled'}`} onClick={onClick}>
      <div className="settings-object-avatar">{initials(profile.name) || <SlidersHorizontal size={16} />}</div>
      <div className="settings-object-copy">
        <strong>{profile.name || t('settings:objectList.untitledModel')}</strong>
        <small>{profile.alias || t('settings:objectList.noProfileKey')} / {architecture} / {profile.provider_model_id || t('settings:objectList.noModelRef')}</small>
      </div>
      <span className={`settings-status-dot ${profile.enabled ? 'enabled' : ''}`}>{profile.enabled ? t('enabled') : t('disabled')}</span>
    </button>
  );
}

function VisionProfileListItem({ profile, active, onClick }: { profile: VisionModelProfile; active: boolean; onClick: () => void }) {
  const { t } = useTranslation(['common', 'settings']);
  return (
    <button type="button" className={`settings-object-row ${active ? 'active' : ''} ${profile.enabled ? '' : 'disabled'}`} onClick={onClick}>
      <div className="settings-object-avatar">{initials(profile.name) || <SlidersHorizontal size={16} />}</div>
      <div className="settings-object-copy">
        <strong>{profile.name || t('settings:objectList.untitledModel')}</strong>
        <small>{profile.alias || t('settings:objectList.noProfileKey')} / {`arch:${profile.architecture}`} / {profile.provider_model_id || t('settings:objectList.noModelRef')}</small>
      </div>
      <span className={`settings-status-dot ${profile.enabled ? 'enabled' : ''}`}>{profile.enabled ? t('enabled') : t('disabled')}</span>
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
  const { t } = useTranslation(['common', 'status', 'knowledge']);
  const profile = embeddingProfiles.find((item) => item.id === knowledgeBase.embedding_model_profile_id);
  const profileName = knowledgeBase.embedding_model_profile_name || profile?.name || t('status:common.unavailable');
  const providerModelId = profile?.provider_model_id || '';
  const legacyModelPath = knowledgeBase.embedding_model_profile_model_path || profile?.model_path || '';
  const profileTitle = [
    knowledgeBase.embedding_model_profile_alias || profile?.alias ? `${t('knowledge:labels.profileKey')}: ${knowledgeBase.embedding_model_profile_alias || profile?.alias}` : '',
    providerModelId ? `${t('knowledge:labels.providerModelId')}: ${providerModelId}` : '',
    !providerModelId && legacyModelPath ? `${t('knowledge:labels.legacyModelPath')}: ${legacyModelPath}` : '',
  ].filter(Boolean).join('\n');
  return (
    <button type="button" className={`settings-object-row ${active ? 'active' : ''} ${knowledgeBase.enabled ? '' : 'disabled'}`} onClick={onClick}>
      <div className="settings-object-avatar">{initials(knowledgeBase.name) || <SlidersHorizontal size={16} />}</div>
      <div className="settings-object-copy">
        <strong>{knowledgeBase.name || 'Untitled knowledge base'}</strong>
        <div className="settings-object-chip-row">
          <StatusChip tone={knowledgeIndexTone(knowledgeBase.index_status || 'empty')}>{getKnowledgeIndexStatusLabel(knowledgeBase.index_status || 'empty', t)}</StatusChip>
          <StatusChip tone="neutral" title={profileTitle}>{profileName}</StatusChip>
        </div>
      </div>
      <span className={`settings-status-dot ${knowledgeBase.enabled ? 'enabled' : ''}`}>{knowledgeBase.enabled ? t('enabled') : t('disabled')}</span>
    </button>
  );
}

function knowledgeIndexTone(status: string): 'neutral' | 'active' | 'warning' | 'danger' {
  if (status === 'ready') return 'active';
  if (status === 'indexing') return 'warning';
  if (['needs_reindex', 'needs_index', 'failed'].includes(status)) return 'danger';
  return 'neutral';
}

function AgentListItem({ config, active, onClick }: { config: AgentConfig; active: boolean; onClick: () => void }) {
  const { t } = useTranslation('common');
  const display = getResolvedAgentDisplay(config);
  const label = display.name || config.agent_id;
  return (
    <button type="button" className={`settings-object-row ${active ? 'active' : ''} ${config.enabled ? '' : 'disabled'}`} onClick={onClick}>
      <AgentAvatar agent={display} label={label} className="settings-object-avatar" iconSize={16} />
      <div className="settings-object-copy">
        <strong>{label}</strong>
        <small>{display.description || config.agent_id}</small>
      </div>
      <span className={`settings-status-dot ${config.enabled ? 'enabled' : ''}`}>{config.enabled ? t('enabled') : t('disabled')}</span>
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
  const { t } = useTranslation('common');
  const summary = config.manifest_summary;
  const label = summary.name || config.capability_id;
  return (
    <button type="button" className={`settings-object-row ${active ? 'active' : ''} ${config.enabled ? '' : 'disabled'}`} onClick={onClick}>
      <div className="settings-object-avatar">{initials(label) || <Boxes size={16} />}</div>
      <div className="settings-object-copy">
        <strong>{label}</strong>
        <small>{config.capability_id}</small>
      </div>
      <span className={`settings-status-dot ${config.enabled ? 'enabled' : ''}`}>{config.enabled ? t('enabled') : t('disabled')}</span>
    </button>
  );
}
