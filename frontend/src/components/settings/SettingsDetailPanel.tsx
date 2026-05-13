import { Activity, Database, Play, RefreshCw, Save, Search, Settings, Trash2 } from 'lucide-react';
import { FormEvent, type ReactNode, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../api/client';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { Agent, AgentConfig, CapabilityConfig, Command, Diagnostics, EmbeddingModelProfile, GeneralSettings, HealthDetails, LlmProfile, LlmProviderProfile, SemanticRouterStatus, StorageStats, UtilityLlmModelScan, UtilityLlmStatus } from '../../types';
import { AgentDetail } from './AgentDetail';
import { CapabilityDetail } from './CapabilityDetail';
import { LlmDefaultsDetail, LlmProfileDetail, LlmProviderProfileDetail, LlmSettingsPanel } from './LlmSettingsPanel';
import { SettingsApiError, toSettingsError, type SettingsErrorValue } from './SettingsApiError';
import { getStatusLabel } from '../../i18n/formatters';
import { ToggleSwitch } from './ToggleSwitch';
import { buildUserConfig, initialConfigValues, isConfigDirty, type ConfigValues } from './configUtils';
import type { KnowledgeSettingsSubsection, LlmSettingsSubsection, SettingsSection, WorldbookSettingsSubsection } from './SettingsNav';
import type { AppearanceSettingsCategory, GeneralSettingsCategory, KnowledgeSettingsCategory, WorldbookSettingsCategory } from './SettingsObjectList';
import { KnowledgeSettingsDetail } from './KnowledgeSettingsPanel';
import { PetSettingsDetail } from './PetSettingsPanel';
import { WorldbookSettingsDetail } from './WorldbookSettingsPanel';

export function SettingsDetailPanel({
  section,
  selectedAgent,
  selectedAgentConfig,
  selectedCapabilityConfig,
  commands,
  health,
  llmProfiles = [],
  llmProviderProfiles = [],
  selectedLlmItemId = 'global',
  llmSubsection = 'defaults',
  generalCategory = 'files',
  appearanceCategory = 'pet',
  knowledgeSubsection = 'defaults',
  selectedKnowledgeItemId = 'global',
  worldbookSubsection = 'defaults',
  selectedWorldbookItemId = 'global',
  onLlmProfilesChanged,
  onKnowledgeObjectsChanged,
  onWorldbookObjectsChanged,
  onSelectGeneralCategory,
  activeTab,
  onTabChange,
  onDirtyChange,
}: {
  section: SettingsSection;
  selectedAgent?: Agent;
  selectedAgentConfig?: AgentConfig;
  selectedCapabilityConfig?: CapabilityConfig;
  commands: Command[];
  health?: HealthDetails;
  llmProfiles?: LlmProfile[];
  llmProviderProfiles?: LlmProviderProfile[];
  selectedLlmItemId?: string;
  llmSubsection?: LlmSettingsSubsection;
  generalCategory?: GeneralSettingsCategory;
  appearanceCategory?: AppearanceSettingsCategory;
  knowledgeSubsection?: KnowledgeSettingsSubsection;
  selectedKnowledgeItemId?: string;
  worldbookSubsection?: WorldbookSettingsSubsection;
  selectedWorldbookItemId?: string;
  onLlmProfilesChanged?: (selectedProfileId?: string) => Promise<void>;
  onKnowledgeObjectsChanged?: (selectedItemId?: string) => Promise<void>;
  onWorldbookObjectsChanged?: (selectedItemId?: string) => Promise<void>;
  onSelectGeneralCategory?: (category: GeneralSettingsCategory) => void;
  activeTab: string;
  onTabChange: (tab: string) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  if (section === 'agents') {
    return (
      <section className="settings-detail-panel">
        {selectedAgentConfig ? (
          <AgentDetail
            config={selectedAgentConfig}
            agent={selectedAgent}
            activeTab={activeTab}
            onTabChange={onTabChange}
            onDirtyChange={onDirtyChange}
          />
        ) : (
          <EmptyDetail title="No agent selected" message="Select an agent from the list." />
        )}
      </section>
    );
  }

  if (section === 'capabilities') {
    return (
      <section className="settings-detail-panel">
        {selectedCapabilityConfig ? (
          <CapabilityDetail
            config={selectedCapabilityConfig}
            commands={commands}
            activeTab={activeTab}
            onTabChange={onTabChange}
            onDirtyChange={onDirtyChange}
          />
        ) : (
          <EmptyDetail title="No capability selected" message="Select a capability from the list." />
        )}
      </section>
    );
  }

  if (section === 'llm') {
    return (
      <section className="settings-detail-panel">
        {llmSubsection === 'defaults' ? (
          <LlmDefaultsDetail profiles={llmProfiles} providerProfiles={llmProviderProfiles} onDirtyChange={onDirtyChange} />
        ) : llmSubsection === 'providers' ? (
          <LlmProviderProfileDetail
            profiles={llmProviderProfiles}
            selectedProfileId={selectedLlmItemId === 'new-provider' ? 'new' : selectedLlmItemId.replace(/^provider:/, '')}
            onProfilesChanged={onLlmProfilesChanged || (async () => undefined)}
            onDirtyChange={onDirtyChange}
          />
        ) : (
          <LlmProfileDetail
            profiles={llmProfiles}
            providerProfiles={llmProviderProfiles}
            selectedProfileId={selectedLlmItemId}
            onProfilesChanged={onLlmProfilesChanged || (async () => undefined)}
            onDirtyChange={onDirtyChange}
          />
        )}
      </section>
    );
  }

  if (section === 'general') {
    return (
      <section className="settings-detail-panel">
        <GeneralDetail category={generalCategory} llmProfiles={llmProfiles} onDirtyChange={onDirtyChange} onSelectGeneralCategory={onSelectGeneralCategory} />
      </section>
    );
  }

  if (section === 'appearance') {
    return (
      <section className="settings-detail-panel">
        {appearanceCategory === 'pet' ? (
          <PetSettingsDetail activeTab={activeTab} onTabChange={onTabChange} onDirtyChange={onDirtyChange} />
        ) : (
          <ChatStatusPanelDetail onDirtyChange={onDirtyChange} />
        )}
      </section>
    );
  }

  if (section === 'knowledge') {
    return (
      <section className="settings-detail-panel">
        <KnowledgeSettingsDetail
          category={knowledgeSubsection as KnowledgeSettingsCategory}
          selectedItemId={selectedKnowledgeItemId}
          onObjectsChanged={onKnowledgeObjectsChanged}
          onDirtyChange={onDirtyChange}
        />
      </section>
    );
  }

  if (section === 'worldbook') {
    return (
      <section className="settings-detail-panel">
        <WorldbookSettingsDetail
          category={worldbookSubsection as WorldbookSettingsCategory}
          selectedItemId={selectedWorldbookItemId}
          onObjectsChanged={onWorldbookObjectsChanged}
          onDirtyChange={onDirtyChange}
        />
      </section>
    );
  }

  if (section === 'data') {
    return (
      <section className="settings-detail-panel">
        <DataDetail health={health} onDirtyChange={onDirtyChange} />
      </section>
    );
  }

  if (section === 'diagnostics') {
    return (
      <section className="settings-detail-panel">
        <DiagnosticsDetail />
      </section>
    );
  }

  return (
    <section className="settings-detail-panel">
      <PlaceholderDetail section={section} />
    </section>
  );
}

function LlmDetail({ config, onDirtyChange }: { config: CapabilityConfig; onDirtyChange: (dirty: boolean) => void }) {
  const { t } = useTranslation('common');
  const { updateCapabilityConfig, savingConfigId, testingLlm } = useWorkbenchStore();
  const [enabled, setEnabled] = useState(config.enabled);
  const [values, setValues] = useState<ConfigValues>(() => initialConfigValues(config));
  const [localError, setLocalError] = useState<SettingsErrorValue | null>(null);
  const [llmBusy, setLlmBusy] = useState(false);
  const dirty = isConfigDirty(config, enabled, values);
  const isSaving = savingConfigId === 'capability:llm';
  const saveDisabled = isSaving || testingLlm || llmBusy;

  useEffect(() => {
    setEnabled(config.enabled);
    setValues(initialConfigValues(config));
    setLocalError(null);
    setLlmBusy(false);
  }, [config]);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  async function save(event: FormEvent) {
    event.preventDefault();
    try {
      setLocalError(null);
      await updateCapabilityConfig('llm', { enabled, user_config: buildUserConfig(config.config_schema || [], values) });
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to save LLM config.'));
    }
  }

  return (
    <form className={`settings-detail-form ${enabled ? '' : 'disabled'}`} onSubmit={save}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">
            <Settings size={18} />
          </div>
          <div>
            <h2>LLM</h2>
            <p>
              <code>llm</code>
              <span>capability config</span>
            </p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {dirty ? (
            <button className="settings-primary-button" type="submit" disabled={saveDisabled}>
              <Save size={14} />
              {isSaving ? t('saving') : t('save')}
            </button>
          ) : null}
          <ToggleSwitch checked={enabled} onChange={setEnabled} disabled={isSaving} />
        </div>
      </header>
      <div className="settings-detail-body">
        <div className="settings-page-intro">
          <h2>LLM</h2>
          <p>OpenAI-compatible local LLM configuration</p>
        </div>
        {localError ? <SettingsApiError error={localError} /> : null}
        <LlmSettingsPanel config={config} values={values} onValuesChange={setValues} showProfiles={false} onBusyChange={setLlmBusy} />
      </div>
    </form>
  );
}

function GeneralDetail({
  category,
  llmProfiles,
  onDirtyChange,
}: {
  category: GeneralSettingsCategory;
  llmProfiles: LlmProfile[];
  onDirtyChange: (dirty: boolean) => void;
  onSelectGeneralCategory?: (category: GeneralSettingsCategory) => void;
}) {
  const { t } = useTranslation(['settings', 'common']);
  const { generalSettings, refreshGeneralSettings, updateGeneralSettings } = useWorkbenchStore();
  const [values, setValues] = useState<GeneralSettings | null>(generalSettings || null);
  const [localError, setLocalError] = useState<SettingsErrorValue | null>(null);
  const [saved, setSaved] = useState(false);
  const dirty = Boolean(values && generalSettings && JSON.stringify(values) !== JSON.stringify(generalSettings));
  const title = category === 'files' ? t('settings:general.files') : category === 'memory' ? t('settings:general.memory') : category === 'utility_llm' ? t('settings:general.utilityLlm') : category === 'intent_routing' ? t('settings:general.intentRouting') : t('settings:general.llmPrompts');
  const description = category === 'files' ? t('settings:general.filesDescription') : category === 'memory' ? t('settings:general.memoryDescription') : category === 'utility_llm' ? t('settings:general.utilityLlmDescription') : category === 'intent_routing' ? t('settings:general.intentRoutingDescription') : t('settings:general.llmPromptsDescription');

  useEffect(() => {
    void refreshGeneralSettings();
  }, [refreshGeneralSettings]);

  useEffect(() => {
    if (generalSettings) setValues(generalSettings);
  }, [generalSettings]);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!values) return;
    try {
      setLocalError(null);
      await updateGeneralSettings(generalSettingsPatch(values));
      setSaved(true);
      window.setTimeout(() => setSaved(false), 1400);
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to save general settings.'));
    }
  }

  function setNumber(key: keyof GeneralSettings, value: string) {
    setValues((current) => (current ? { ...current, [key]: Number(value) } : current));
  }

  function setString(key: keyof GeneralSettings, value: string) {
    setValues((current) => (current ? { ...current, [key]: value } : current));
  }

  function setInstruction(key: 'session_title_prompt' | 'group_transcript_system_instruction' | 'command_result_context_instruction', value: string) {
    setValues((current) => (current ? { ...current, [key]: value } : current));
  }

  function resetInstruction(key: 'session_title_prompt' | 'group_transcript_system_instruction' | 'command_result_context_instruction') {
    setValues((current) => {
      if (!current) return current;
      if (key === 'session_title_prompt') {
        return { ...current, session_title_prompt: current.session_title_prompt_default };
      }
      if (key === 'group_transcript_system_instruction') {
        return {
          ...current,
          group_transcript_system_instruction: null,
          group_transcript_system_instruction_effective: current.group_transcript_system_instruction_default,
        };
      }
      return {
        ...current,
        command_result_context_instruction: null,
        command_result_context_instruction_effective: current.command_result_context_instruction_default,
      };
    });
  }

  if (!values) return <EmptyDetail title={t('settings:sections.general')} message={t('settings:general.loading')} />;

  return (
    <form className="settings-detail-form" onSubmit={save}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">
            <Settings size={18} />
          </div>
          <div>
            <h2>{title}</h2>
            <p>{description}</p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {saved ? <span className="settings-badge success">{t('common:saved')}</span> : null}
          {dirty ? (
            <button className="settings-primary-button" type="submit">
              <Save size={14} />
              {t('common:save')}
            </button>
          ) : null}
        </div>
      </header>
      <div className="settings-detail-body">
        {localError ? <SettingsApiError error={localError} /> : null}
        {category === 'files' ? (
          <GeneralFilesSettings values={values} setValues={setValues} setNumber={setNumber} />
        ) : category === 'memory' ? (
          <GeneralMemorySettings values={values} setValues={setValues} />
        ) : category === 'utility_llm' ? (
          <GeneralUtilityLlmSettings values={values} setValues={setValues} setNumber={setNumber} setString={setString} />
        ) : category === 'intent_routing' ? (
          <GeneralIntentRoutingSettings values={values} setValues={setValues} setNumber={setNumber} setString={setString} />
        ) : (
          <GeneralPromptSettings values={values} llmProfiles={llmProfiles} setValues={setValues} setNumber={setNumber} setInstruction={setInstruction} resetInstruction={resetInstruction} />
        )}
      </div>
    </form>
  );
}

function ChatStatusPanelDetail({ onDirtyChange }: { onDirtyChange: (dirty: boolean) => void }) {
  const { t } = useTranslation(['settings', 'common']);
  const { generalSettings, refreshGeneralSettings, updateGeneralSettings } = useWorkbenchStore();
  const [values, setValues] = useState<GeneralSettings | null>(generalSettings || null);
  const [localError, setLocalError] = useState<SettingsErrorValue | null>(null);
  const [saved, setSaved] = useState(false);
  const dirty = Boolean(values && generalSettings && JSON.stringify(resourceStatusSettingsPatch(values)) !== JSON.stringify(resourceStatusSettingsPatch(generalSettings)));

  useEffect(() => {
    void refreshGeneralSettings();
  }, [refreshGeneralSettings]);

  useEffect(() => {
    if (generalSettings) setValues(generalSettings);
  }, [generalSettings]);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!values) return;
    try {
      setLocalError(null);
      await updateGeneralSettings(resourceStatusSettingsPatch(values));
      setSaved(true);
      window.setTimeout(() => setSaved(false), 1400);
    } catch (error) {
      setLocalError(toSettingsError(error, t('settings:appearance.saveChatStatusPanelFailed')));
    }
  }

  if (!values) return <EmptyDetail title={t('settings:appearance.chatStatusPanel')} message={t('settings:general.loading')} />;

  return (
    <form className="settings-detail-form" onSubmit={save}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">
            <Activity size={18} />
          </div>
          <div>
            <h2>{t('settings:appearance.chatStatusPanel')}</h2>
            <p>{t('settings:appearance.chatStatusPanelDescription')}</p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {saved ? <span className="settings-badge success">{t('common:saved')}</span> : null}
          {dirty ? (
            <button className="settings-primary-button" type="submit">
              <Save size={14} />
              {t('common:save')}
            </button>
          ) : null}
        </div>
      </header>
      <div className="settings-detail-body">
        {localError ? <SettingsApiError error={localError} /> : null}
        <div className="detail-section">
          <div className="detail-section-heading">
            <h3>{t('settings:appearance.chatStatusPanel')}</h3>
          </div>
          <label className="config-field settings-config-field boolean-field">
            <span>{t('settings:appearance.enableResourceStatusPanel')}</span>
            <ToggleSwitch checked={values.resource_status_panel_enabled} onChange={(checked) => setValues({ ...values, resource_status_panel_enabled: checked })} />
          </label>
          <div className="settings-detail-grid">
            <BooleanField label={t('settings:appearance.showCpu')} checked={values.resource_status_show_cpu} onChange={(checked) => setValues({ ...values, resource_status_show_cpu: checked })} />
            <BooleanField label={t('settings:appearance.showRam')} checked={values.resource_status_show_ram} onChange={(checked) => setValues({ ...values, resource_status_show_ram: checked })} />
            <BooleanField label={t('settings:appearance.showGpu')} checked={values.resource_status_show_gpu} onChange={(checked) => setValues({ ...values, resource_status_show_gpu: checked })} />
            <BooleanField label={t('settings:appearance.showVram')} checked={values.resource_status_show_vram} onChange={(checked) => setValues({ ...values, resource_status_show_vram: checked })} />
            <DisplayModeField label={t('settings:appearance.ramDisplayMode')} value={values.resource_status_ram_display_mode} onChange={(mode) => setValues({ ...values, resource_status_ram_display_mode: mode })} />
            <DisplayModeField label={t('settings:appearance.vramDisplayMode')} value={values.resource_status_vram_display_mode} onChange={(mode) => setValues({ ...values, resource_status_vram_display_mode: mode })} />
          </div>
        </div>
        <div className="detail-section">
          <div className="detail-section-heading">
            <h3>{t('settings:appearance.tokens')}</h3>
          </div>
          <label className="config-field settings-config-field boolean-field">
            <span>{t('settings:appearance.showSessionTokens')}</span>
            <ToggleSwitch checked={values.resource_status_show_tokens} onChange={(checked) => setValues({ ...values, resource_status_show_tokens: checked })} />
          </label>
        </div>
      </div>
    </form>
  );
}

function BooleanField({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <label className="config-field settings-config-field boolean-field">
      <span>{label}</span>
      <ToggleSwitch checked={checked} onChange={onChange} />
    </label>
  );
}

function DisplayModeField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: 'percent' | 'value';
  onChange: (value: 'percent' | 'value') => void;
}) {
  const { t } = useTranslation('settings');
  return (
    <label className="config-field settings-config-field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.currentTarget.value as 'percent' | 'value')}>
        <option value="percent">{t('appearance.percent')}</option>
        <option value="value">{t('appearance.value')}</option>
      </select>
    </label>
  );
}

function resourceStatusSettingsPatch(values: GeneralSettings): Partial<GeneralSettings> {
  return {
    resource_status_panel_enabled: values.resource_status_panel_enabled,
    resource_status_show_cpu: values.resource_status_show_cpu,
    resource_status_show_ram: values.resource_status_show_ram,
    resource_status_show_gpu: values.resource_status_show_gpu,
    resource_status_show_vram: values.resource_status_show_vram,
    resource_status_ram_display_mode: values.resource_status_ram_display_mode,
    resource_status_vram_display_mode: values.resource_status_vram_display_mode,
    resource_status_show_tokens: values.resource_status_show_tokens,
  };
}

function GeneralFilesSettings({
  values,
  setValues,
  setNumber,
}: {
  values: GeneralSettings;
  setValues: (values: GeneralSettings) => void;
  setNumber: (key: keyof GeneralSettings, value: string) => void;
}) {
  const { t } = useTranslation('settings');
  return (
    <>
      <div className="detail-section">
        <div className="detail-section-heading">
          <h3>{t('general.uploadLimits')}</h3>
        </div>
        <div className="settings-detail-grid">
          <NumberField label={t('general.maxImageSize')} value={values.max_image_size_mb} min={1} max={100} onChange={(value) => setNumber('max_image_size_mb', value)} />
          <NumberField label={t('general.maxFileSize')} value={values.max_file_size_mb} min={1} max={100} onChange={(value) => setNumber('max_file_size_mb', value)} />
          <NumberField label={t('general.maxAttachments')} value={values.max_attachments_per_message} min={1} max={50} onChange={(value) => setNumber('max_attachments_per_message', value)} />
        </div>
      </div>
      <div className="detail-section">
        <div className="detail-section-heading">
          <h3>{t('general.llmFileContext')}</h3>
        </div>
        <label className="config-field settings-config-field boolean-field">
          <span>{t('general.sendTextFiles')}</span>
          <ToggleSwitch checked={values.send_text_file_attachments_to_llm} onChange={(checked) => setValues({ ...values, send_text_file_attachments_to_llm: checked })} />
          <small>{t('general.sendTextFilesHelp')}</small>
        </label>
        <div className="settings-detail-grid">
          <NumberField label={t('general.maxFileContextPerFile')} value={values.max_file_context_per_file_kb} min={1} max={2048} onChange={(value) => setNumber('max_file_context_per_file_kb', value)} />
          <NumberField label={t('general.maxTotalFileContext')} value={values.max_total_file_context_per_message_kb} min={1} max={8192} onChange={(value) => setNumber('max_total_file_context_per_message_kb', value)} />
        </div>
      </div>
    </>
  );
}

function GeneralPromptSettings({
  values,
  llmProfiles,
  setValues,
  setNumber,
  setInstruction,
  resetInstruction,
}: {
  values: GeneralSettings;
  llmProfiles: LlmProfile[];
  setValues: (values: GeneralSettings) => void;
  setNumber: (key: keyof GeneralSettings, value: string) => void;
  setInstruction: (key: 'session_title_prompt' | 'group_transcript_system_instruction' | 'command_result_context_instruction', value: string) => void;
  resetInstruction: (key: 'session_title_prompt' | 'group_transcript_system_instruction' | 'command_result_context_instruction') => void;
}) {
  const { t } = useTranslation('settings');
  const selectedTitleProfile = values.session_title_model_profile_id
    ? llmProfiles.find((profile) => profile.id === values.session_title_model_profile_id)
    : null;
  const titleProfileMissing = Boolean(values.session_title_model_profile_id && !selectedTitleProfile);
  const titleProfileDisabled = Boolean(selectedTitleProfile && !selectedTitleProfile.enabled);
  return (
    <>
      <div className="detail-section">
        <div className="detail-section-heading">
          <h3>{t('general.sessionTitles')}</h3>
        </div>
        <label className="config-field settings-config-field boolean-field">
          <span>{t('general.autoGenerateTitles')}</span>
          <ToggleSwitch checked={values.auto_generate_session_titles} onChange={(checked) => setValues({ ...values, auto_generate_session_titles: checked })} />
          <small>{t('general.autoGenerateTitlesHelp')}</small>
        </label>
        <label className="config-field settings-config-field">
          <span>{t('general.titleGenerationBackend')}</span>
          <select
            value={values.session_title_backend}
            onChange={(event) =>
              setValues({
                ...values,
                session_title_backend: event.currentTarget.value as GeneralSettings['session_title_backend'],
              })
            }
          >
            <option value="utility_llm">{t('general.titleBackendUtilityLlm')}</option>
            <option value="follow_agent_model_profile">{t('general.titleBackendFollowAgent')}</option>
            <option value="specified_model_profile">{t('general.titleBackendSpecificProfile')}</option>
          </select>
          <small>{t('general.titleBackendHelp')}</small>
        </label>
        {values.session_title_backend === 'specified_model_profile' ? (
          <label className="config-field settings-config-field">
            <span>{t('general.specificTitleModelProfile')}</span>
            <select
              value={values.session_title_model_profile_id || ''}
              onChange={(event) =>
                setValues({
                  ...values,
                  session_title_model_profile_id: event.currentTarget.value || null,
                })
              }
            >
              <option value="">{t('general.noModelProfileSelected')}</option>
              {llmProfiles
                .filter((profile) => profile.enabled || profile.id === values.session_title_model_profile_id)
                .map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {titleModelProfileOptionLabel(profile)}
                  </option>
                ))}
            </select>
            <small>{t('general.specificTitleModelProfileHelp')}</small>
          </label>
        ) : null}
        {titleProfileMissing ? <p className="settings-warning-text">{t('general.selectedModelProfileUnavailable')}</p> : null}
        {titleProfileDisabled ? <p className="settings-warning-text">{t('general.selectedModelProfileDisabled')}</p> : null}
        <label className="config-field settings-config-field boolean-field">
          <span>{t('general.freeTitleModelAfterGeneration')}</span>
          <ToggleSwitch checked={values.session_title_unload_after_generation} onChange={(checked) => setValues({ ...values, session_title_unload_after_generation: checked })} />
          <small>{t('general.freeTitleModelAfterGenerationHelp')}</small>
        </label>
        <InstructionField
          label={t('general.sessionTitlePrompt')}
          description={t('general.sessionTitlePromptHelp')}
          value={values.session_title_prompt}
          isDefault={values.session_title_prompt === values.session_title_prompt_default}
          onChange={(value) => setInstruction('session_title_prompt', value)}
          onReset={() => resetInstruction('session_title_prompt')}
        />
        <div className="settings-detail-grid">
          <NumberField label={t('general.sessionTitleMaxChars')} value={values.session_title_max_input_chars} min={100} max={10000} onChange={(value) => setNumber('session_title_max_input_chars', value)} />
        </div>
      </div>
      <div className="detail-section">
        <div className="detail-section-heading">
          <h3>{t('general.contextRendering')}</h3>
        </div>
        <InstructionField
          label={t('general.groupTranscriptInstruction')}
          description={t('general.groupTranscriptInstructionHelp')}
          value={values.group_transcript_system_instruction ?? values.group_transcript_system_instruction_effective}
          isDefault={values.group_transcript_system_instruction === null}
          onChange={(value) => setInstruction('group_transcript_system_instruction', value)}
          onReset={() => resetInstruction('group_transcript_system_instruction')}
        />
        <InstructionField
          label={t('general.commandResultInstruction')}
          description={t('general.commandResultInstructionHelp')}
          value={values.command_result_context_instruction ?? values.command_result_context_instruction_effective}
          isDefault={values.command_result_context_instruction === null}
          onChange={(value) => setInstruction('command_result_context_instruction', value)}
          onReset={() => resetInstruction('command_result_context_instruction')}
        />
      </div>
    </>
  );
}

function GeneralMemorySettings({ values, setValues }: { values: GeneralSettings; setValues: (values: GeneralSettings) => void }) {
  const { t } = useTranslation('settings');
  return (
    <div className="detail-section">
      <div className="detail-section-heading">
        <h3>{t('general.coreMemory')}</h3>
      </div>
      <label className="config-field settings-config-field">
        <span>{t('general.coreMemoryContent')}</span>
        <textarea rows={12} value={values.core_memory_content} onChange={(event) => setValues({ ...values, core_memory_content: event.currentTarget.value })} />
        <small>{t('general.coreMemoryHelp')}</small>
      </label>
      <label className="config-field settings-config-field boolean-field">
        <span>{t('general.enableForPromptAgents')}</span>
        <ToggleSwitch checked={values.core_memory_enabled_for_prompt_agents} onChange={(checked) => setValues({ ...values, core_memory_enabled_for_prompt_agents: checked })} />
      </label>
      <label className="config-field settings-config-field boolean-field">
        <span>{t('general.enableForScriptAgents')}</span>
        <ToggleSwitch checked={values.core_memory_enabled_for_script_agents} onChange={(checked) => setValues({ ...values, core_memory_enabled_for_script_agents: checked })} />
      </label>
    </div>
  );
}

function titleModelProfileOptionLabel(profile: LlmProfile): string {
  const pieces = [profile.name || profile.alias || profile.id, profile.alias, profile.provider].filter(Boolean);
  return pieces.join(' / ');
}

function GeneralIntentRoutingSettings({
  values,
  setValues,
  setNumber,
  setString,
}: {
  values: GeneralSettings;
  setValues: (values: GeneralSettings) => void;
  setNumber: (key: keyof GeneralSettings, value: string) => void;
  setString: (key: keyof GeneralSettings, value: string) => void;
}) {
  const { t } = useTranslation(['settings', 'common']);
  const [status, setStatus] = useState<UtilityLlmStatus | null>(null);
  const [semanticStatus, setSemanticStatus] = useState<SemanticRouterStatus | null>(null);
  const [busy, setBusy] = useState('');
  const [routeTestText, setRouteTestText] = useState('');
  const [routeTestResult, setRouteTestResult] = useState<Record<string, unknown> | null>(null);
  const [embeddingProfiles, setEmbeddingProfiles] = useState<EmbeddingModelProfile[]>([]);
  const [error, setError] = useState<SettingsErrorValue | null>(null);
  const selectedProfile = embeddingProfiles.find((profile) => profile.id === values.intent_routing_embedding_model_profile_id);
  const missingSelectedProfile = Boolean(values.intent_routing_embedding_model_profile_id && !selectedProfile);
  const disabledSelectedProfile = Boolean(selectedProfile && !selectedProfile.enabled);

  async function refreshStatus() {
    try {
      setError(null);
      const [utility, semantic] = await Promise.all([api.getUtilityLlmStatus(), api.getSemanticRouterStatus()]);
      setStatus(utility);
      setSemanticStatus(semantic);
    } catch (err) {
      setError(toSettingsError(err, t('settings:general.utilityLlmStatusFailed')));
    }
  }

  useEffect(() => {
    void refreshStatus();
  }, [values.intent_routing_utility_llm_backend, values.intent_routing_utility_llm_model_path, values.intent_routing_embedding_model_profile_id]);

  useEffect(() => {
    void api.listEmbeddingModels()
      .then(setEmbeddingProfiles)
      .catch((err) => setError(toSettingsError(err, t('settings:general.embeddingProfilesFailed'))));
  }, [t]);

  async function runRouteTest() {
    if (!routeTestText.trim()) return;
    setBusy('route-test');
    try {
      setError(null);
      const response = await api.testIntentRoute({ text: routeTestText, include_utility: Boolean(values.intent_routing_utility_llm_model_path) });
      setRouteTestResult(response.decision);
    } catch (err) {
      setError(toSettingsError(err, t('settings:general.routeTestFailed')));
    } finally {
      setBusy('');
    }
  }

  return (
    <>
      <div className="detail-section">
        <div className="detail-section-heading">
          <h3>{t('settings:general.intentRouting')}</h3>
        </div>
        <div className="settings-hint-callout">
          <ul>
            <li>{t('settings:general.intentRoutingExplicitBypass')}</li>
            <li>{t('settings:general.intentRoutingShadowRecords')}</li>
            <li>{t('settings:general.intentRoutingAutoSafeOnly')}</li>
          </ul>
        </div>
        <label className="config-field settings-config-field boolean-field">
          <span>{t('settings:general.enableIntentRouting')}</span>
          <ToggleSwitch checked={values.intent_routing_enabled} onChange={(checked) => setValues({ ...values, intent_routing_enabled: checked })} />
        </label>
        <label className="config-field settings-config-field boolean-field">
          <span>{t('settings:general.defaultForPromptAgents')}</span>
          <ToggleSwitch checked={values.intent_routing_default_for_prompt_agents} onChange={(checked) => setValues({ ...values, intent_routing_default_for_prompt_agents: checked })} />
          <small>{t('settings:general.defaultForPromptAgentsHelp')}</small>
        </label>
        <label className="config-field settings-config-field">
          <span>{t('settings:general.intentRoutingMode')}</span>
          <select value={values.intent_routing_mode} onChange={(event) => setString('intent_routing_mode', event.currentTarget.value)}>
            <option value="shadow">{t('settings:general.shadowMode')}</option>
            <option value="auto">{t('settings:general.autoMode')}</option>
          </select>
          <small>{values.intent_routing_mode === 'auto' ? t('settings:general.autoModeHelp') : t('settings:general.shadowModeHelp')}</small>
        </label>
        {values.intent_routing_mode === 'auto' && !values.intent_routing_auto_route_safe_intents ? (
          <p className="settings-warning-text">{t('settings:general.autoModeSafeRoutingOff')}</p>
        ) : null}
        <label className="config-field settings-config-field boolean-field">
          <span>{t('settings:general.autoRouteSafeIntents')}</span>
          <ToggleSwitch checked={values.intent_routing_auto_route_safe_intents} onChange={(checked) => setValues({ ...values, intent_routing_auto_route_safe_intents: checked })} />
          <small>{t('settings:general.autoRouteSafeIntentsHelp')}</small>
        </label>
        <label className="config-field settings-config-field boolean-field">
          <span>{t('settings:general.confirmUncertainRoutes')}</span>
          <ToggleSwitch checked={values.intent_routing_confirm_uncertain} onChange={(checked) => setValues({ ...values, intent_routing_confirm_uncertain: checked })} />
          <small>{t('settings:general.plannedForLater')}</small>
        </label>
      </div>
      <div className="detail-section">
        <div className="detail-section-heading">
          <h3>{t('settings:general.semanticRouter')}</h3>
        </div>
        {error ? <SettingsApiError error={error} /> : null}
        <label className="config-field settings-config-field">
          <span>{t('settings:general.embeddingModelProfile')}</span>
          <select
            value={values.intent_routing_embedding_model_profile_id || ''}
            onChange={(event) =>
              setValues({
                ...values,
                intent_routing_embedding_model_profile_id: event.currentTarget.value || null,
              })
            }
          >
            <option value="">{t('settings:general.noEmbeddingProfileSelected')}</option>
            {embeddingProfiles.filter((profile) => profile.enabled || profile.id === values.intent_routing_embedding_model_profile_id).map((profile) => (
              <option key={profile.id} value={profile.id}>
                {embeddingProfileOptionLabel(profile, t)}
              </option>
            ))}
          </select>
          <small>{t('settings:general.embeddingProfileHelp')}</small>
        </label>
        {missingSelectedProfile ? <p className="settings-warning-text">{t('settings:general.selectedEmbeddingProfileUnavailable')}</p> : null}
        {disabledSelectedProfile ? <p className="settings-warning-text">{t('settings:general.selectedEmbeddingProfileDisabled')}</p> : null}
        <div className="settings-inline-summary">
          <span>{t('settings:general.semanticRouterStatus')}</span>
          <strong>{semanticStatus ? semanticRouterStatusText(semanticStatus.status, t) : t('settings:general.semanticRouterStatusLoading')}</strong>
          <small>{semanticStatus?.index?.will_rebuild_lazily ? t('settings:general.semanticIndexWillRebuild') : t('settings:general.semanticIndexReady')}</small>
        </div>
        {semanticStatus ? (
          <dl className="settings-definition-grid semantic-candidate-summary">
            <Metric label={t('settings:general.intentExamplesCount')} value={String(semanticStatus.candidate_summary.intent_examples)} wide />
            <Metric label={t('settings:general.kbCandidatesCount')} value={String(semanticStatus.candidate_summary.knowledge_bases)} />
            <Metric label={t('settings:general.agentCandidatesCount')} value={String(semanticStatus.candidate_summary.agents)} />
            <Metric label={t('settings:general.actionCandidatesCount')} value={String(semanticStatus.candidate_summary.actions)} />
            <Metric label={t('settings:general.commandCandidatesCount')} value={String(semanticStatus.candidate_summary.commands)} />
          </dl>
        ) : null}
        <div className="settings-inline-summary">
          <span>{t('settings:general.utilityLlm')}</span>
          <strong>{status ? utilityStatusText(status, t) : t('settings:general.utilityLlmStatusLoading')}</strong>
          <small>{t('settings:general.utilityLlmSummaryLine', { backend: status?.backend || values.intent_routing_utility_llm_backend, model: status?.model_path || values.intent_routing_utility_llm_model_path || t('settings:general.utilityLlmNotConfigured') })}</small>
        </div>
        <details className="settings-disclosure">
          <summary>{t('settings:general.semanticThresholds')}</summary>
          <div className="settings-detail-grid">
            <NumberField label={t('settings:general.intentMinScore')} value={values.intent_routing_semantic_intent_min_score} min={0} max={1} step={0.01} onChange={(value) => setNumber('intent_routing_semantic_intent_min_score', value)} />
            <NumberField label={t('settings:general.intentMinMargin')} value={values.intent_routing_semantic_intent_min_margin} min={0} max={1} step={0.01} onChange={(value) => setNumber('intent_routing_semantic_intent_min_margin', value)} />
            <NumberField label={t('settings:general.kbMinScore')} value={values.intent_routing_semantic_kb_min_score} min={0} max={1} step={0.01} onChange={(value) => setNumber('intent_routing_semantic_kb_min_score', value)} />
            <NumberField label={t('settings:general.agentMinScore')} value={values.intent_routing_semantic_agent_min_score} min={0} max={1} step={0.01} onChange={(value) => setNumber('intent_routing_semantic_agent_min_score', value)} />
            <NumberField label={t('settings:general.commandMinScore')} value={values.intent_routing_semantic_command_min_score} min={0} max={1} step={0.01} onChange={(value) => setNumber('intent_routing_semantic_command_min_score', value)} />
          </div>
        </details>
      </div>
      <div className="detail-section">
        <div className="detail-section-heading">
          <h3>{t('settings:general.routeExamples')}</h3>
        </div>
        <p className="settings-muted-text">{t('settings:general.routeExamplesHelp')}</p>
        <p className="settings-muted-text">{t('settings:general.routeExamplesSafetyHelp')}</p>
        <div className="settings-detail-grid">
          <TextAreaField label={t('settings:general.chatExamples')} value={values.intent_routing_chat_examples} onChange={(value) => setString('intent_routing_chat_examples', value)} />
          <TextAreaField label={t('settings:general.imageGenerationExamples')} value={values.intent_routing_image_generation_examples} onChange={(value) => setString('intent_routing_image_generation_examples', value)} />
          <TextAreaField label={t('settings:general.knowledgeQueryExamples')} value={values.intent_routing_knowledge_query_examples} onChange={(value) => setString('intent_routing_knowledge_query_examples', value)} />
          <TextAreaField label={t('settings:general.agentRouteExamples')} value={values.intent_routing_agent_route_examples} onChange={(value) => setString('intent_routing_agent_route_examples', value)} />
          <TextAreaField label={t('settings:general.commandLikeExamples')} value={values.intent_routing_command_like_examples} onChange={(value) => setString('intent_routing_command_like_examples', value)} />
        </div>
        <small className="settings-muted-text">{t('settings:general.oneExamplePerLine')}</small>
      </div>
      <div className="detail-section">
        <div className="detail-section-heading">
          <h3>{t('settings:general.routeTest')}</h3>
        </div>
        <p className="settings-muted-text">{t('settings:general.routeTestHelp')}</p>
        <label className="config-field settings-config-field">
          <span>{t('settings:general.routeTestInput')}</span>
          <textarea rows={3} value={routeTestText} onChange={(event) => setRouteTestText(event.currentTarget.value)} />
        </label>
        <div className="settings-button-row">
          <button type="button" className="settings-secondary-button" disabled={Boolean(busy) || !routeTestText.trim()} onClick={() => void runRouteTest()}>
            <Play size={14} />
            {busy === 'route-test' ? t('common:loading') : t('settings:general.testRoute')}
          </button>
        </div>
        {routeTestResult ? <RouteTestResult decision={routeTestResult} /> : null}
      </div>
    </>
  );
}

function GeneralUtilityLlmSettings({
  values,
  setValues,
  setNumber,
  setString,
}: {
  values: GeneralSettings;
  setValues: (values: GeneralSettings) => void;
  setNumber: (key: keyof GeneralSettings, value: string) => void;
  setString: (key: keyof GeneralSettings, value: string) => void;
}) {
  const { t } = useTranslation(['settings', 'common']);
  const [status, setStatus] = useState<UtilityLlmStatus | null>(null);
  const [busy, setBusy] = useState('');
  const [result, setResult] = useState('');
  const [modelScan, setModelScan] = useState<UtilityLlmModelScan | null>(null);
  const [error, setError] = useState<SettingsErrorValue | null>(null);

  async function refreshStatus() {
    try {
      setError(null);
      setStatus(await api.getUtilityLlmStatus());
    } catch (err) {
      setError(toSettingsError(err, t('settings:general.utilityLlmStatusFailed')));
    }
  }

  useEffect(() => {
    void refreshStatus();
  }, [
    values.intent_routing_utility_llm_backend,
    values.intent_routing_utility_llm_model_path,
    values.intent_routing_device,
    values.intent_routing_utility_llm_context_size,
    values.intent_routing_utility_llm_gpu_layers,
    values.intent_routing_utility_llm_threads,
  ]);

  async function scanModels() {
    setBusy('scan-utility');
    try {
      setError(null);
      const response = await api.scanUtilityLlmModels();
      setModelScan(response);
      if (!response.transformers_models.length && !response.gguf_models.length) {
        setResult(t('settings:general.noUtilityLlmModelsFound'));
      } else if (response.warnings.includes('root_gguf_ignored')) {
        setResult(t('settings:general.rootGgufIgnored'));
      } else {
        setResult(t('settings:general.utilityLlmScanComplete'));
      }
    } catch (err) {
      setError(toSettingsError(err, t('settings:general.utilityLlmScanFailed')));
    } finally {
      setBusy('');
    }
  }

  async function runUtilityAction(action: 'title' | 'json' | 'unload') {
    setBusy(action);
    try {
      setError(null);
      if (action === 'title') {
        const response = await api.testUtilityLlmTitle(t('settings:general.utilityLlmSampleTitleInput'));
        setResult(t('settings:general.utilityLlmTitleResult', { title: response.title }));
      } else if (action === 'json') {
        const response = await api.testUtilityLlmJson(t('settings:general.utilityLlmSampleJsonInput'));
        setResult(t('settings:general.utilityLlmJsonResult', { intent: response.result.intent, confidence: response.result.confidence }));
      } else {
        await api.unloadUtilityLlm();
        setResult(t('settings:general.utilityLlmUnloaded'));
      }
      await refreshStatus();
    } catch (err) {
      setError(toSettingsError(err, t('settings:general.utilityLlmActionFailed')));
    } finally {
      setBusy('');
    }
  }

  return (
    <>
      <div className="detail-section">
        <div className="detail-section-heading">
          <h3>{t('settings:general.utilityLlm')}</h3>
        </div>
        <p className="settings-muted-text">{t('settings:general.utilityLlmHelp')}</p>
        <p className="settings-muted-text">{t('settings:general.utilityLlmNotProfileHelp')}</p>
        <label className="config-field settings-config-field">
          <span>{t('settings:general.utilityLlmBackend')}</span>
          <select
            value={values.intent_routing_utility_llm_backend}
            onChange={(event) =>
              setValues({
                ...values,
                intent_routing_utility_llm_backend: event.currentTarget.value as GeneralSettings['intent_routing_utility_llm_backend'],
              })
            }
          >
            <option value="transformers">{t('settings:general.utilityLlmBackendTransformers')}</option>
            <option value="llama_cpp">{t('settings:general.utilityLlmBackendLlamaCpp')}</option>
          </select>
        </label>
        <label className="config-field settings-config-field">
          <span>{values.intent_routing_utility_llm_backend === 'llama_cpp' ? t('settings:general.ggufModelPath') : t('settings:general.utilityLlmModelPath')}</span>
          <select value={values.intent_routing_utility_llm_model_path} onChange={(event) => setString('intent_routing_utility_llm_model_path', event.currentTarget.value)}>
            <option value="">{t('settings:general.none')}</option>
            {utilityModelOptions(modelScan, values.intent_routing_utility_llm_backend, values.intent_routing_utility_llm_model_path, t).map((model) => (
              <option key={model.model_path} value={model.model_path}>
                {model.label}
              </option>
            ))}
          </select>
          <small>{values.intent_routing_utility_llm_backend === 'llama_cpp' ? t('settings:general.ggufPathHelp') : t('settings:general.utilityLlmPathHelp')}</small>
        </label>
        <div className="settings-button-row">
          <button type="button" className="settings-secondary-button" disabled={Boolean(busy)} onClick={() => void scanModels()}>
            <Search size={14} />
            {busy === 'scan-utility' ? t('common:loading') : t('settings:general.scanUtilityLlmModels')}
          </button>
        </div>
        {modelScan?.warnings.includes('root_gguf_ignored') ? <p className="settings-warning-text">{t('settings:general.rootGgufIgnored')}</p> : null}
      </div>
      <div className="detail-section">
        <div className="detail-section-heading">
          <h3>{t('settings:general.runtimeOptions')}</h3>
        </div>
        <div className="settings-detail-grid">
          <NumberField label={t('settings:general.contextSize')} value={values.intent_routing_utility_llm_context_size} min={512} max={32768} step={1} onChange={(value) => setNumber('intent_routing_utility_llm_context_size', value)} />
          <NumberField label={t('settings:general.gpuLayers')} value={values.intent_routing_utility_llm_gpu_layers} min={-1} max={200} step={1} onChange={(value) => setNumber('intent_routing_utility_llm_gpu_layers', value)} />
          <label className="config-field settings-config-field">
            <span>{t('settings:general.threads')}</span>
            <input
              type="number"
              min={1}
              max={128}
              value={values.intent_routing_utility_llm_threads ?? ''}
              placeholder={t('settings:general.backendDefault')}
              onChange={(event) =>
                setValues({
                  ...values,
                  intent_routing_utility_llm_threads: event.currentTarget.value ? Number(event.currentTarget.value) : null,
                })
              }
            />
          </label>
          <label className="config-field settings-config-field">
            <span>{t('settings:general.device')}</span>
            <select value={values.intent_routing_device} onChange={(event) => setString('intent_routing_device', event.currentTarget.value)}>
              <option value="auto">{t('settings:general.deviceAuto')}</option>
              <option value="cpu">{t('settings:general.deviceCpu')}</option>
              <option value="cuda">{t('settings:general.deviceCuda')}</option>
            </select>
            <small>{t('settings:general.utilityLlmDeviceHelp')}</small>
          </label>
        </div>
      </div>
      <div className="detail-section">
        <div className="detail-section-heading">
          <h3>{t('settings:general.utilityLlmStatus')}</h3>
        </div>
        {error ? <SettingsApiError error={error} /> : null}
        <div className="settings-card">
          <div className="settings-card-header">
            <div className="settings-card-title-row">
              <strong>{t('settings:general.utilityLlmStatus')}</strong>
              {status ? <span className={`status-chip utility-status-chip ${utilityStatusTone(status)}`}>{utilityStatusChipText(status, t)}</span> : <span className="status-chip utility-status-chip muted">{t('common:loading')}</span>}
            </div>
            <div className="settings-card-actions">
              <button type="button" className="settings-secondary-button" onClick={() => void refreshStatus()} disabled={Boolean(busy)}>
                <RefreshCw size={14} />
                {t('common:refresh')}
              </button>
              <button type="button" className="settings-secondary-button" disabled={Boolean(busy)} onClick={() => void runUtilityAction('title')}>
                {busy === 'title' ? t('common:loading') : t('settings:general.testTitleGeneration')}
              </button>
              <button type="button" className="settings-secondary-button" disabled={Boolean(busy)} onClick={() => void runUtilityAction('json')}>
                {busy === 'json' ? t('common:loading') : t('settings:general.testJsonExtraction')}
              </button>
              <button type="button" className="settings-secondary-button" disabled={Boolean(busy)} onClick={() => void runUtilityAction('unload')}>
                {busy === 'unload' ? t('common:loading') : t('settings:general.unloadUtilityLlm')}
              </button>
            </div>
          </div>
          {status ? (
            <dl className="settings-definition-grid utility-status-grid">
              <Metric label={t('settings:general.utilityLlmBackend')} value={status.backend} />
              <Metric label={t('settings:general.utilityLlmModelPath')} value={status.model_path || t('settings:general.utilityLlmNotConfigured')} wide valueClassName="settings-mono-value" />
              <Metric label={t('settings:general.statusConfigured')} value={status.configured ? t('settings:general.yes') : t('settings:general.no')} />
              <Metric label={t('settings:general.statusAvailable')} value={status.available ? t('settings:general.yes') : t('settings:general.no')} />
              <Metric label={t('settings:general.statusLoaded')} value={status.loaded ? t('settings:general.yes') : t('settings:general.no')} />
              <Metric label={t('settings:general.resolvedDevice')} value={status.resolved_device || t('settings:general.notAvailable')} />
              <Metric label={t('settings:general.modelPathStatus')} value={utilityModelPathStatus(status, t)} />
              <Metric label={t('settings:general.dependencies')} value={<UtilityDependencyChips status={status} />} wide valueClassName="settings-definition-capabilities" />
            </dl>
          ) : null}
          {result ? <p className="settings-muted-text">{result}</p> : null}
        </div>
      </div>
    </>
  );
}

function utilityStatusText(status: UtilityLlmStatus, t: ReturnType<typeof useTranslation>['t']): string {
  if (!status.configured) return t('settings:general.utilityLlmNotConfigured');
  if (!status.available) {
    if (status.reason === 'UTILITY_LLM_BACKEND_UNAVAILABLE') return t('settings:general.utilityLlmDepsUnavailable');
    if (status.reason === 'llama_cpp_unavailable') return t('settings:general.llamaCppUnavailable');
    if (status.reason === 'model_not_found') return t('settings:general.utilityLlmModelNotFound');
    if (status.reason === 'model_path_invalid') return t('settings:general.utilityLlmInvalidPath');
    if (status.reason === 'backend_model_path_mismatch') return t('settings:general.utilityLlmBackendPathMismatch');
    return t('settings:general.utilityLlmUnavailable');
  }
  return status.loaded ? t('settings:general.utilityLlmLoaded') : t('settings:general.utilityLlmReady');
}

function utilityStatusChipText(status: UtilityLlmStatus, t: ReturnType<typeof useTranslation>['t']): string {
  if (!status.configured) return t('settings:general.notConfigured');
  if (status.loaded) return t('settings:general.statusLoaded');
  if (status.available) return t('settings:general.statusAvailable');
  return t('settings:general.unavailable');
}

function utilityStatusTone(status: UtilityLlmStatus): 'active' | 'warning' | 'danger' {
  if (status.loaded || status.available) return 'active';
  if (!status.configured) return 'warning';
  return 'danger';
}

function utilityModelPathStatus(status: UtilityLlmStatus, t: ReturnType<typeof useTranslation>['t']): string {
  if (!status.configured) return t('settings:general.utilityLlmNotConfigured');
  if (status.reason === 'model_not_found') return t('settings:general.missing');
  if (status.reason === 'model_path_invalid' || status.reason === 'backend_model_path_mismatch') return t('settings:general.invalid');
  return status.available ? t('settings:general.ok') : status.reason || t('settings:general.notAvailable');
}

function UtilityDependencyChips({ status }: { status: UtilityLlmStatus }) {
  const { t } = useTranslation('settings');
  const dependencies = [
    { label: t('general.transformersAvailable'), available: status.backend_status.transformers_available },
    { label: t('general.torchAvailable'), available: status.backend_status.torch_available },
    { label: t('general.llamaCppAvailable'), available: status.backend_status.llama_cpp_available },
    { label: t('general.cudaAvailable'), available: status.backend_status.cuda_available },
  ];
  return (
    <span className="settings-chip-row compact utility-dependency-chips">
      {dependencies.map((dependency) => (
        <span key={dependency.label} className={dependency.available ? 'available' : 'unavailable'}>
          {dependency.label}: {dependency.available ? t('general.yes') : t('general.no')}
        </span>
      ))}
    </span>
  );
}

function utilityModelOptions(scan: UtilityLlmModelScan | null, backend: GeneralSettings['intent_routing_utility_llm_backend'], currentPath: string, t: ReturnType<typeof useTranslation>['t']): { model_path: string; label: string }[] {
  const models = backend === 'llama_cpp' ? scan?.gguf_models || [] : scan?.transformers_models || [];
  const options = models.map((model) => ({
    model_path: model.model_path,
    label: backend === 'llama_cpp' && model.folder ? `${model.folder} / ${model.name}` : model.name,
  }));
  if (currentPath && !options.some((option) => option.model_path === currentPath)) {
    options.unshift({ model_path: currentPath, label: `${currentPath} (${scan ? t('settings:general.notFound') : t('settings:general.notScanned')})` });
  }
  return options;
}

function embeddingProfileOptionLabel(profile: EmbeddingModelProfile, t: ReturnType<typeof useTranslation>['t']): string {
  const status = profile.enabled ? '' : ` (${t('common:disabled')})`;
  return `${profile.name} / ${profile.alias} / ${profile.model_path}${status}`;
}

function generalSettingsPatch(values: GeneralSettings): Partial<GeneralSettings> {
  return {
    max_image_size_mb: values.max_image_size_mb,
    max_file_size_mb: values.max_file_size_mb,
    max_attachments_per_message: values.max_attachments_per_message,
    max_file_context_per_file_kb: values.max_file_context_per_file_kb,
    max_total_file_context_per_message_kb: values.max_total_file_context_per_message_kb,
    send_text_file_attachments_to_llm: values.send_text_file_attachments_to_llm,
    persist_streaming_message_deltas: values.persist_streaming_message_deltas,
    auto_generate_session_titles: values.auto_generate_session_titles,
    session_title_backend: values.session_title_backend,
    session_title_model_profile_id: values.session_title_model_profile_id,
    session_title_unload_after_generation: values.session_title_unload_after_generation,
    session_title_prompt: values.session_title_prompt,
    session_title_max_input_chars: values.session_title_max_input_chars,
    group_transcript_system_instruction: values.group_transcript_system_instruction,
    command_result_context_instruction: values.command_result_context_instruction,
    core_memory_content: values.core_memory_content,
    core_memory_enabled_for_prompt_agents: values.core_memory_enabled_for_prompt_agents,
    core_memory_enabled_for_script_agents: values.core_memory_enabled_for_script_agents,
    intent_routing_enabled: values.intent_routing_enabled,
    intent_routing_default_for_prompt_agents: values.intent_routing_default_for_prompt_agents,
    intent_routing_mode: values.intent_routing_mode,
    intent_routing_semantic_intent_min_score: values.intent_routing_semantic_intent_min_score,
    intent_routing_semantic_intent_min_margin: values.intent_routing_semantic_intent_min_margin,
    intent_routing_semantic_kb_min_score: values.intent_routing_semantic_kb_min_score,
    intent_routing_semantic_agent_min_score: values.intent_routing_semantic_agent_min_score,
    intent_routing_semantic_command_min_score: values.intent_routing_semantic_command_min_score,
    intent_routing_auto_route_safe_intents: values.intent_routing_auto_route_safe_intents,
    intent_routing_confirm_uncertain: values.intent_routing_confirm_uncertain,
    intent_routing_embedding_model_profile_id: values.intent_routing_embedding_model_profile_id,
    intent_routing_utility_llm_backend: values.intent_routing_utility_llm_backend,
    intent_routing_utility_llm_model_path: values.intent_routing_utility_llm_model_path,
    intent_routing_utility_llm_context_size: values.intent_routing_utility_llm_context_size,
    intent_routing_utility_llm_gpu_layers: values.intent_routing_utility_llm_gpu_layers,
    intent_routing_utility_llm_threads: values.intent_routing_utility_llm_threads,
    intent_routing_device: values.intent_routing_device,
    intent_routing_chat_examples: values.intent_routing_chat_examples,
    intent_routing_image_generation_examples: values.intent_routing_image_generation_examples,
    intent_routing_knowledge_query_examples: values.intent_routing_knowledge_query_examples,
    intent_routing_agent_route_examples: values.intent_routing_agent_route_examples,
    intent_routing_command_like_examples: values.intent_routing_command_like_examples,
  };
}

function RouteTestResult({ decision }: { decision: Record<string, unknown> }) {
  const { t } = useTranslation(['settings', 'common']);
  const slots = typeof decision.slots === 'object' && decision.slots ? decision.slots : {};
  const topCandidates = Array.isArray(decision.top_candidates) ? decision.top_candidates.slice(0, 6) : [];
  const thresholds = typeof decision.semantic_thresholds_used === 'object' && decision.semantic_thresholds_used ? decision.semantic_thresholds_used as Record<string, unknown> : {};
  const groupScores = Array.isArray(decision.intent_group_scores) ? decision.intent_group_scores.slice(0, 5) : [];
  const score = typeof decision.intent_score === 'number' ? decision.intent_score : decision.semantic_score;
  const margin = typeof decision.intent_margin === 'number' ? decision.intent_margin : decision.semantic_margin;
  const reason = readableRouteReason(String(decision.not_executed_reason || decision.diagnostic_reason || decision.bypass_reason || ''), t, score, margin, thresholds);
  return (
    <>
      <h4 className="settings-compact-subheading">{t('settings:general.executionSummary')}</h4>
      <dl className="settings-definition-grid">
        <Metric label={t('settings:general.predictedIntent')} value={String(decision.predicted_intent || decision.bypass_reason || t('settings:general.none'))} />
        <Metric label={t('settings:general.wouldExecute')} value={decision.would_execute ? t('settings:general.yes') : t('settings:general.no')} />
        <Metric label={t('settings:general.routeAction')} value={String(decision.route_action || t('settings:general.none'))} />
        <Metric label={t('settings:general.notExecutedReason')} value={reason || (decision.would_execute ? t('settings:general.wouldExecuteYesReason') : t('settings:general.none'))} />
        <Metric label={t('settings:general.scoreMargin')} value={`${typeof score === 'number' ? score.toFixed(2) : t('settings:general.none')} / ${typeof margin === 'number' ? margin.toFixed(2) : t('settings:general.none')}`} />
        {decision.predicted_intent === 'pet_command' ? (
          <>
            <Metric label={t('settings:general.petAction')} value={String(decision.pet_action || t('settings:general.none'))} />
            <Metric label={t('settings:general.targetPet')} value={petSummary(decision, 'target', t)} />
            <Metric label={t('settings:general.sourcePet')} value={petSummary(decision, 'source', t)} />
            <Metric label={t('settings:general.generatedPetCommand')} value={String(decision.generated_command || t('settings:general.none'))} />
          </>
        ) : null}
        <Metric label={t('settings:general.temporaryKnowledgeBaseOverride')} value={Array.isArray(decision.temporary_knowledge_base_ids) ? decision.temporary_knowledge_base_ids.join(', ') || t('settings:general.none') : t('settings:general.none')} />
        <Metric label={t('settings:general.knowledgeQueryOverride')} value={String(decision.knowledge_query_override || t('settings:general.none'))} />
      </dl>
      <details className="settings-disclosure route-test-diagnostics">
        <summary>{t('settings:general.diagnostics')}</summary>
        <dl className="settings-definition-grid">
          <Metric label={t('settings:general.source')} value={String(decision.source || t('settings:general.none'))} />
          <Metric label={t('settings:general.confidence')} value={typeof decision.confidence === 'number' ? decision.confidence.toFixed(2) : t('settings:general.none')} />
          <Metric label={t('settings:general.semanticScore')} value={typeof decision.semantic_score === 'number' ? decision.semantic_score.toFixed(2) : t('settings:general.none')} />
          <Metric label={t('settings:general.semanticMargin')} value={typeof decision.semantic_margin === 'number' ? decision.semantic_margin.toFixed(2) : t('settings:general.none')} />
          <Metric label={t('settings:general.secondIntent')} value={String(decision.second_intent || t('settings:general.none'))} />
          <Metric label={t('settings:general.semanticThresholds')} value={formatThresholds(thresholds, t)} />
          <Metric label={t('settings:general.intentGroupScores')} value={groupScores.map((item) => candidateSummary(item, t)).join(' | ') || t('settings:general.none')} wide />
          <Metric label={t('settings:general.autoExecutable')} value={decision.auto_executable ? t('settings:general.yes') : t('settings:general.no')} />
          <Metric label={t('settings:general.targetAgent')} value={String(decision.target_agent_id || t('settings:general.none'))} />
          <Metric label={t('settings:general.targetAction')} value={String(decision.target_action_id || t('settings:general.none'))} />
          <Metric label={t('settings:general.targetCommand')} value={String(decision.target_command || t('settings:general.none'))} />
          <Metric label={t('settings:general.kbCandidate')} value={candidateSummary(decision.kb_candidate, t)} />
          <Metric label={t('settings:general.agentCandidate')} value={candidateSummary(decision.agent_candidate, t)} />
          <Metric label={t('settings:general.actionCandidate')} value={candidateSummary(decision.action_candidate, t)} />
          <Metric label={t('settings:general.commandCandidate')} value={candidateSummary(decision.command_candidate, t)} />
          <Metric label={t('settings:general.slots')} value={JSON.stringify(slots)} wide />
          <Metric label={t('settings:general.warnings')} value={Array.isArray(decision.warnings) ? decision.warnings.join(', ') || t('settings:general.none') : t('settings:general.none')} wide />
        </dl>
        {topCandidates.length ? (
          <div className="settings-inline-summary">
            <span>{t('settings:general.topCandidates')}</span>
            <small>{topCandidates.map((candidate) => candidateSummary(candidate, t)).join(' | ')}</small>
          </div>
        ) : null}
      </details>
    </>
  );
}

function readableRouteReason(code: string, t: ReturnType<typeof useTranslation>['t'], score: unknown, margin: unknown, thresholds: Record<string, unknown>): string {
  if (!code) return '';
  if (code === 'semantic_intent_score_below_threshold' && typeof score === 'number' && typeof thresholds.intent_min_score === 'number') {
    return t('settings:general.scoreBelowThresholdDetail', { score: score.toFixed(2), threshold: thresholds.intent_min_score.toFixed(2) });
  }
  if (code === 'semantic_margin_below_threshold' && typeof margin === 'number' && typeof thresholds.intent_min_margin === 'number') {
    return t('settings:general.marginBelowThresholdDetail', { margin: margin.toFixed(2), threshold: thresholds.intent_min_margin.toFixed(2) });
  }
  return t(`settings:general.routeReason.${code}`, { defaultValue: code });
}

function formatThresholds(thresholds: Record<string, unknown>, t: ReturnType<typeof useTranslation>['t']): string {
  const pieces = ['intent_min_score', 'intent_min_margin', 'kb_min_score'].map((key) => {
    const value = thresholds[key];
    return typeof value === 'number' ? `${key} ${value.toFixed(2)}` : '';
  }).filter(Boolean);
  return pieces.join(' / ') || t('settings:general.none');
}

function semanticRouterStatusText(status: string, t: (key: string) => string): string {
  if (status === 'ready') return t('settings:general.semanticStatusReady');
  if (status === 'no_profile_selected') return t('settings:general.semanticStatusNoProfile');
  if (status === 'profile_unavailable') return t('settings:general.semanticStatusProfileUnavailable');
  if (status === 'embedding_backend_unavailable') return t('settings:general.semanticStatusBackendUnavailable');
  return status || t('settings:general.unavailable');
}

function candidateSummary(value: unknown, t: (key: string) => string): string {
  if (!value || typeof value !== 'object') return t('settings:general.none');
  const candidate = value as Record<string, unknown>;
  const label = candidate.intent || candidate.kb_name || candidate.agent_id || candidate.action_id || candidate.command_name || candidate.kind || t('settings:general.none');
  const score = typeof candidate.score === 'number' ? ` ${candidate.score.toFixed(2)}` : '';
  const field = candidate.field ? ` ${String(candidate.field)}` : '';
  return `${String(label)}${field}${score}`;
}

function petSummary(decision: Record<string, unknown>, kind: 'target' | 'source', t: (key: string) => string): string {
  const id = decision[`${kind}_pet_id`];
  const hint = decision[`${kind}_pet_hint`];
  const name = decision[`${kind}_pet_name`];
  const pieces = [name, id, hint].filter((item) => typeof item === 'string' && item.trim());
  return pieces.length ? pieces.map(String).join(' / ') : t('settings:general.none');
}

function InstructionField({
  label,
  description,
  value,
  isDefault,
  onChange,
  onReset,
}: {
  label: string;
  description: string;
  value: string;
  isDefault: boolean;
  onChange: (value: string) => void;
  onReset: () => void;
}) {
  const { t } = useTranslation(['common', 'settings']);
  return (
    <label className="config-field settings-config-field">
      <span>
        {label}
        <button className="settings-secondary-button" type="button" onClick={onReset} disabled={isDefault}>
          {t('reset')}
        </button>
      </span>
      <textarea rows={6} value={value} onChange={(event) => onChange(event.currentTarget.value)} />
      <small>
        {description} {isDefault ? t('settings:general.usingDefaultValue') : t('settings:general.usingSavedOverride')}
      </small>
    </label>
  );
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="config-field settings-config-field">
      <span>{label}</span>
      <input value={value} onChange={(event) => onChange(event.currentTarget.value)} />
    </label>
  );
}

function TextAreaField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="config-field settings-config-field">
      <span>{label}</span>
      <textarea rows={5} value={value} onChange={(event) => onChange(event.currentTarget.value)} />
    </label>
  );
}

function NumberField({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step?: number; onChange: (value: string) => void }) {
  return (
    <label className="config-field settings-config-field">
      <span>{label}</span>
      <input type="number" min={min} max={max} step={step} value={value} onChange={(event) => onChange(event.currentTarget.value)} />
    </label>
  );
}

function DataDetail({ health, onDirtyChange }: { health?: HealthDetails; onDirtyChange: (dirty: boolean) => void }) {
  const { t } = useTranslation(['common', 'settings', 'status']);
  const { generalSettings, refreshGeneralSettings, updateGeneralSettings } = useWorkbenchStore();
  const [stats, setStats] = useState<StorageStats | null>(null);
  const [busy, setBusy] = useState('');
  const [localError, setLocalError] = useState<SettingsErrorValue | null>(null);
  const [confirmClean, setConfirmClean] = useState(false);
  const [persistDeltas, setPersistDeltas] = useState(false);
  const [saved, setSaved] = useState(false);
  const dirty = Boolean(generalSettings && persistDeltas !== generalSettings.persist_streaming_message_deltas);

  async function refresh() {
    setBusy('refresh');
    try {
      setLocalError(null);
      setStats(await api.getStorageStats());
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to load storage stats.'));
    } finally {
      setBusy('');
    }
  }

  useEffect(() => {
    void refresh();
    void refreshGeneralSettings();
  }, []);

  useEffect(() => {
    if (generalSettings) setPersistDeltas(generalSettings.persist_streaming_message_deltas);
  }, [generalSettings]);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  async function saveSettings() {
    try {
      setLocalError(null);
      await updateGeneralSettings({ persist_streaming_message_deltas: persistDeltas });
      setSaved(true);
      window.setTimeout(() => setSaved(false), 1400);
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to save data settings.'));
    }
  }

  async function scan() {
    setBusy('scan');
    try {
      setLocalError(null);
      await api.scanOrphanAttachments();
      await refresh();
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to scan orphan attachments.'));
      setBusy('');
    }
  }

  async function clean() {
    if (!confirmClean) {
      setConfirmClean(true);
      return;
    }
    setBusy('clean');
    try {
      setLocalError(null);
      await api.cleanupOrphanAttachments(true);
      setConfirmClean(false);
      await refresh();
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to clean orphan attachments.'));
      setBusy('');
    }
  }

  const orphanCount = stats?.attachments.orphan_count ?? 0;

  return (
    <div className="settings-detail-form">
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">
            <Database size={18} />
          </div>
          <div>
            <h2>{t('settings:data.title')}</h2>
            <p>{t('settings:data.description')}</p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {saved ? <span className="settings-badge success">{t('saved')}</span> : null}
          {dirty ? (
            <button className="settings-primary-button" type="button" onClick={saveSettings}>
              <Save size={14} />
              {t('save')}
            </button>
          ) : null}
        </div>
      </header>
      <div className="settings-detail-body">
        {localError ? <SettingsApiError error={localError} /> : null}
        <div className="detail-section">
          <div className="detail-section-heading">
            <h3>{t('settings:data.eventLog')}</h3>
          </div>
          <label className="config-field settings-config-field boolean-field">
            <span>{t('settings:data.persistDeltas')}</span>
            <ToggleSwitch checked={persistDeltas} onChange={setPersistDeltas} />
            <small>{t('settings:data.persistDeltasHelp')}</small>
          </label>
        </div>
        <div className="detail-section">
          <div className="detail-section-heading">
            <h3>{t('settings:data.database')}</h3>
          </div>
          <dl className="settings-definition-grid">
            <Metric label={t('settings:data.status')} value={getStatusLabel(stats?.database.status || health?.database?.status || 'unavailable', t)} />
            <Metric label={t('settings:data.schemaVersion')} value={stats?.database.schema_version || health?.schema_version || t('status:common.unavailable')} />
            <Metric label={t('settings:data.databasePath')} value={stats?.database.path || t('status:common.unavailable')} wide />
            <Metric label={t('settings:data.databaseSize')} value={formatBytes(stats?.database.size_bytes || 0)} />
          </dl>
        </div>
        <div className="detail-section">
          <div className="detail-section-heading">
            <h3>{t('settings:data.attachments')}</h3>
          </div>
          <dl className="settings-definition-grid">
            <Metric label={t('settings:data.directory')} value={stats?.attachments.directory || t('status:common.unavailable')} wide />
            <Metric label={t('settings:data.attachmentCount')} value={String(stats?.attachments.count ?? 0)} />
            <Metric label={t('settings:data.totalSize')} value={formatBytes(stats?.attachments.total_size_bytes || 0)} />
            <Metric label={t('settings:data.orphanCount')} value={String(orphanCount)} />
            <Metric label={t('settings:data.orphanSize')} value={formatBytes(stats?.attachments.orphan_size_bytes || 0)} />
          </dl>
        </div>
        <div className="detail-section">
          <div className="detail-section-heading">
            <h3>{t('settings:data.maintenance')}</h3>
          </div>
          <div className="settings-button-row">
            <button className="settings-secondary-button" type="button" onClick={refresh} disabled={Boolean(busy)}>
              <RefreshCw size={14} />
              {t('settings:data.refreshStats')}
            </button>
            <button className="settings-secondary-button" type="button" onClick={scan} disabled={Boolean(busy)}>
              <Search size={14} />
              {t('settings:data.scanOrphans')}
            </button>
            <button className="settings-secondary-button danger" type="button" onClick={clean} disabled={Boolean(busy) || orphanCount === 0}>
              <Trash2 size={14} />
              {confirmClean ? t('settings:data.confirmClean') : t('settings:data.cleanOrphans')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function DiagnosticsDetail() {
  const { t } = useTranslation(['settings', 'status']);
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState<SettingsErrorValue | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<string>('');

  async function refresh() {
    setBusy(true);
    try {
      setLocalError(null);
      setDiagnostics(await api.getDiagnostics());
      setLastRefreshed(new Date().toLocaleTimeString());
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to refresh diagnostics.'));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <div className="settings-detail-form">
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">
            <Activity size={18} />
          </div>
          <div>
            <h2>{t('settings:diagnostics.title')}</h2>
            <p>{t('settings:diagnostics.description')}</p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {lastRefreshed ? <span className="settings-muted-text">{t('settings:diagnostics.lastRefreshed', { time: lastRefreshed })}</span> : null}
          <button className="settings-secondary-button" type="button" onClick={refresh} disabled={busy}>
            <RefreshCw size={14} />
            {busy ? t('settings:diagnostics.refreshing') : t('settings:diagnostics.refresh')}
          </button>
        </div>
      </header>
      <div className="settings-detail-body">
        {localError ? <SettingsApiError error={localError} /> : null}
        {!diagnostics ? (
          <EmptyDetail title={t('settings:diagnostics.title')} message={busy ? t('settings:diagnostics.loading') : t('settings:diagnostics.unavailable')} />
        ) : (
          <>
            <div className="settings-diagnostics-grid">
              <DiagnosticsCard title={t('settings:diagnostics.system')}>
                <Metric label={t('settings:diagnostics.backendStatus')} value={getStatusLabel(diagnostics.backend.status, t)} />
                <Metric label={t('settings:diagnostics.version')} value={diagnostics.backend.version || t('status:common.unknown')} />
                <Metric label={t('settings:diagnostics.python')} value={diagnostics.backend.python_version || t('status:common.unknown')} />
                <Metric label={t('settings:diagnostics.uptime')} value={formatDuration(diagnostics.backend.uptime_seconds || 0)} />
              </DiagnosticsCard>
              <DiagnosticsCard title={t('settings:diagnostics.database')}>
                <Metric label={t('settings:data.status')} value={getStatusLabel(diagnostics.database.status, t)} />
                <Metric label={t('settings:data.schemaVersion')} value={diagnostics.database.schema_version || t('status:common.unknown')} />
                <Metric label={t('settings:data.databaseSize')} value={formatBytes(diagnostics.database.size_bytes || 0)} />
              </DiagnosticsCard>
              <DiagnosticsCard title={t('settings:diagnostics.attachments')}>
                <Metric label={t('settings:data.status')} value={getStatusLabel(diagnostics.attachments.status, t)} />
                <Metric label={t('settings:data.attachmentCount')} value={String(diagnostics.attachments.count ?? 0)} />
                <Metric label={t('settings:data.totalSize')} value={formatBytes(diagnostics.attachments.total_size_bytes || 0)} />
                <Metric label={t('settings:diagnostics.writable')} value={diagnostics.attachments.writable ? t('status:common.yes') : t('status:common.no')} />
              </DiagnosticsCard>
              <DiagnosticsCard title={t('settings:diagnostics.realtime')}>
                <Metric label={t('settings:diagnostics.eventBusSubscribers')} value={String(diagnostics.event_bus.subscriber_count ?? 0)} />
                <Metric label={t('settings:diagnostics.websocketConnections')} value={String(diagnostics.event_bus.active_websocket_connections ?? 0)} />
                <Metric label={t('settings:diagnostics.activeRuns')} value={String(diagnostics.runs.active_count)} />
                <Metric label={t('settings:diagnostics.activeTasks')} value={String(diagnostics.runs.active_task_count ?? 0)} />
              </DiagnosticsCard>
              <DiagnosticsCard title="LLM">
                <Metric label={t('settings:diagnostics.profiles')} value={t('settings:diagnostics.enabledCount', { enabled: diagnostics.llm.profiles_enabled, total: diagnostics.llm.profiles_total })} />
                <Metric label={t('settings:diagnostics.resolvedModel')} value={diagnostics.llm.default_resolved?.model_id || t('status:common.notSelected')} />
                <Metric label={t('settings:diagnostics.baseUrl')} value={diagnostics.llm.default_resolved?.base_url || t('status:common.unavailable')} />
                <Metric label={t('settings:diagnostics.apiKeySet')} value={diagnostics.llm.default_resolved?.api_key_set ? t('status:common.yes') : t('status:common.no')} />
              </DiagnosticsCard>
              <DiagnosticsCard title={t('settings:diagnostics.capabilities')}>
                <Metric label={t('settings:diagnostics.file')} value={`${diagnostics.capabilities.file.enabled ? t('status:common.enabled') : t('status:common.disabled')} / ${getStatusLabel(diagnostics.capabilities.file.status, t)}`} />
                <Metric label={t('settings:diagnostics.allowedDirs')} value={String(diagnostics.capabilities.file.allowed_directories_count ?? 0)} />
                <Metric label="/read-file" value={diagnostics.capabilities.file.read_file_enabled ? t('status:common.enabled') : t('status:common.disabled')} />
                <Metric label="/read-image" value={diagnostics.capabilities.file.read_image_enabled ? t('status:common.enabled') : t('status:common.disabled')} />
                <Metric label={t('settings:diagnostics.maxTextRead')} value={`${diagnostics.capabilities.file.max_local_text_read_size_mb ?? 0} MB`} />
                <Metric label={t('settings:diagnostics.maxImageRead')} value={`${diagnostics.capabilities.file.max_local_image_read_size_mb ?? 0} MB`} />
                <Metric label={t('settings:diagnostics.http')} value={`${diagnostics.capabilities.http.enabled ? t('status:common.enabled') : t('status:common.disabled')} / ${getStatusLabel(diagnostics.capabilities.http.status, t)}`} />
                <Metric label={t('settings:diagnostics.httpGet')} value={diagnostics.capabilities.http.http_get_enabled ? t('status:common.enabled') : t('status:common.disabled')} />
                <Metric label={t('settings:diagnostics.fetchImage')} value={diagnostics.capabilities.http.fetch_image_enabled ? t('status:common.enabled') : t('status:common.disabled')} />
                <Metric label={t('settings:diagnostics.maxTextResponse')} value={`${diagnostics.capabilities.http.max_text_response_size_mb ?? 0} MB`} />
                <Metric label={t('settings:diagnostics.maxImageResponse')} value={`${diagnostics.capabilities.http.max_image_response_size_mb ?? 0} MB`} />
                <Metric label={t('settings:diagnostics.redirects')} value={diagnostics.capabilities.http.allow_redirects ? t('settings:diagnostics.allowed') : t('status:common.disabled')} />
              </DiagnosticsCard>
            </div>
            <div className="detail-section">
              <div className="detail-section-heading">
                <h3>{t('settings:diagnostics.recentFailures')}</h3>
              </div>
              {diagnostics.runs.recent_failures.length ? (
                <div className="settings-table-wrap">
                  <table className="settings-table">
                    <thead>
                      <tr>
                        <th>{t('settings:diagnostics.time')}</th>
                        <th>{t('settings:diagnostics.target')}</th>
                        <th>{t('settings:diagnostics.error')}</th>
                        <th>{t('settings:diagnostics.message')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {diagnostics.runs.recent_failures.map((failure) => (
                        <tr key={failure.run_id}>
                          <td>{formatDateTime(failure.created_at)}</td>
                          <td>{failure.agent_id || failure.command_name || t('settings:diagnostics.run')}</td>
                          <td>{failure.error_code}</td>
                          <td>{failure.message || t('settings:diagnostics.noErrorMessage')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="settings-empty-state compact">{t('settings:diagnostics.noRecentFailures')}</div>
              )}
            </div>
            <div className="detail-section">
              <div className="detail-section-heading">
                <h3>{t('settings:diagnostics.warnings')}</h3>
              </div>
              {diagnostics.warnings.length ? (
                <ul className="settings-warning-list">
                  {diagnostics.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              ) : (
                <div className="settings-empty-state compact">{t('settings:diagnostics.noWarnings')}</div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function DiagnosticsCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="settings-diagnostics-card">
      <h3>{title}</h3>
      <dl className="settings-definition-grid compact">{children}</dl>
    </div>
  );
}

function Metric({ label, value, wide, valueClassName }: { label: string; value: ReactNode; wide?: boolean; valueClassName?: string }) {
  return (
    <div className={wide ? 'wide' : ''}>
      <dt>{label}</dt>
      <dd className={valueClassName} title={typeof value === 'string' ? value : undefined}>{value}</dd>
    </div>
  );
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} KB`;
  if (value < 1024 * 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function PlaceholderDetail({ section }: { section: SettingsSection }) {
  const { t } = useTranslation(['settings', 'common']);
  if (section === 'developer') {
    return (
      <div className="settings-placeholder">
        <h2>{t('settings:developer.title')}</h2>
        <p>{t('settings:developer.description')}</p>
        <ul>
          <li>
            <code>scripts/check_agents.py</code>
          </li>
          <li>
            <code>scripts/run_agent.py</code>
          </li>
          <li>
            <code>docs/AGENT_DEVELOPMENT.md</code>
          </li>
        </ul>
      </div>
    );
  }
  if (section === 'about') {
    return (
      <div className="settings-placeholder">
        <h2>{t('settings:about.title')}</h2>
        <dl className="settings-definition-grid">
          <div>
            <dt>{t('common:version')}</dt>
            <dd>0.1.0-alpha</dd>
          </div>
          <div>
            <dt>{t('settings:about.projectStatus')}</dt>
            <dd>{t('settings:about.technicalAlpha')}</dd>
          </div>
        </dl>
      </div>
    );
  }
  return <EmptyDetail title={t('settings:title')} message={t('settings:placeholder')} />;
}

function EmptyDetail({ title, message }: { title: string; message: string }) {
  return (
    <div className="settings-placeholder">
      <h2>{title}</h2>
      <p>{message}</p>
    </div>
  );
}
