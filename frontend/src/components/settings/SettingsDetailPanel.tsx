import { Activity, Database, RefreshCw, Save, Search, Settings, Trash2 } from 'lucide-react';
import { FormEvent, type ReactNode, useEffect, useState } from 'react';
import { api } from '../../api/client';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { Agent, AgentConfig, CapabilityConfig, Command, Diagnostics, GeneralSettings, HealthDetails, LlmProfile, LlmProviderProfile, StorageStats } from '../../types';
import { AgentDetail } from './AgentDetail';
import { CapabilityDetail } from './CapabilityDetail';
import { LlmDefaultsDetail, LlmProfileDetail, LlmProviderProfileDetail, LlmSettingsPanel } from './LlmSettingsPanel';
import { SettingsApiError, toSettingsError, type SettingsErrorValue } from './SettingsApiError';
import { ToggleSwitch } from './ToggleSwitch';
import { buildUserConfig, initialConfigValues, isConfigDirty, type ConfigValues } from './configUtils';
import type { LlmSettingsSubsection, SettingsSection } from './SettingsNav';
import type { GeneralSettingsCategory, KnowledgeSettingsCategory } from './SettingsObjectList';
import { KnowledgeSettingsDetail } from './KnowledgeSettingsPanel';

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
  knowledgeCategory = 'defaults',
  onLlmProfilesChanged,
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
  knowledgeCategory?: KnowledgeSettingsCategory;
  onLlmProfilesChanged?: (selectedProfileId?: string) => Promise<void>;
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
        <GeneralDetail category={generalCategory} onDirtyChange={onDirtyChange} />
      </section>
    );
  }

  if (section === 'knowledge') {
    return (
      <section className="settings-detail-panel">
        <KnowledgeSettingsDetail category={knowledgeCategory} onDirtyChange={onDirtyChange} />
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
              {isSaving ? 'Saving...' : 'Save'}
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

function GeneralDetail({ category, onDirtyChange }: { category: GeneralSettingsCategory; onDirtyChange: (dirty: boolean) => void }) {
  const { generalSettings, refreshGeneralSettings, updateGeneralSettings } = useWorkbenchStore();
  const [values, setValues] = useState<GeneralSettings | null>(generalSettings || null);
  const [localError, setLocalError] = useState<SettingsErrorValue | null>(null);
  const [saved, setSaved] = useState(false);
  const dirty = Boolean(values && generalSettings && JSON.stringify(values) !== JSON.stringify(generalSettings));
  const title = category === 'files' ? 'Files' : 'LLM & Prompts';
  const description = category === 'files' ? 'Upload limits and file context.' : 'Title generation and context prompts.';

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

  if (!values) return <EmptyDetail title="General" message="Loading general settings." />;

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
          {saved ? <span className="settings-badge success">Saved</span> : null}
          {dirty ? (
            <button className="settings-primary-button" type="submit">
              <Save size={14} />
              Save
            </button>
          ) : null}
        </div>
      </header>
      <div className="settings-detail-body">
        {localError ? <SettingsApiError error={localError} /> : null}
        {category === 'files' ? (
          <GeneralFilesSettings values={values} setValues={setValues} setNumber={setNumber} />
        ) : (
          <GeneralPromptSettings values={values} setValues={setValues} setNumber={setNumber} setInstruction={setInstruction} resetInstruction={resetInstruction} />
        )}
      </div>
    </form>
  );
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
  return (
    <>
      <div className="detail-section">
        <div className="detail-section-heading">
          <h3>Upload limits</h3>
        </div>
        <div className="settings-detail-grid">
          <NumberField label="Max image size (MB)" value={values.max_image_size_mb} min={1} max={100} onChange={(value) => setNumber('max_image_size_mb', value)} />
          <NumberField label="Max file size (MB)" value={values.max_file_size_mb} min={1} max={100} onChange={(value) => setNumber('max_file_size_mb', value)} />
          <NumberField label="Max attachments per message" value={values.max_attachments_per_message} min={1} max={50} onChange={(value) => setNumber('max_attachments_per_message', value)} />
        </div>
      </div>
      <div className="detail-section">
        <div className="detail-section-heading">
          <h3>LLM file context</h3>
        </div>
        <label className="config-field settings-config-field boolean-field">
          <span>Send text file attachments to LLM</span>
          <ToggleSwitch checked={values.send_text_file_attachments_to_llm} onChange={(checked) => setValues({ ...values, send_text_file_attachments_to_llm: checked })} />
          <small>This only affects ordinary text files. Image Vision input is controlled by the selected model.</small>
        </label>
        <div className="settings-detail-grid">
          <NumberField label="Max file context per file (KB)" value={values.max_file_context_per_file_kb} min={1} max={2048} onChange={(value) => setNumber('max_file_context_per_file_kb', value)} />
          <NumberField label="Max total file context per message (KB)" value={values.max_total_file_context_per_message_kb} min={1} max={8192} onChange={(value) => setNumber('max_total_file_context_per_message_kb', value)} />
        </div>
      </div>
    </>
  );
}

function GeneralPromptSettings({
  values,
  setValues,
  setNumber,
  setInstruction,
  resetInstruction,
}: {
  values: GeneralSettings;
  setValues: (values: GeneralSettings) => void;
  setNumber: (key: keyof GeneralSettings, value: string) => void;
  setInstruction: (key: 'session_title_prompt' | 'group_transcript_system_instruction' | 'command_result_context_instruction', value: string) => void;
  resetInstruction: (key: 'session_title_prompt' | 'group_transcript_system_instruction' | 'command_result_context_instruction') => void;
}) {
  return (
    <>
      <div className="detail-section">
        <div className="detail-section-heading">
          <h3>Session titles</h3>
        </div>
        <label className="config-field settings-config-field boolean-field">
          <span>Auto-generate session titles</span>
          <ToggleSwitch checked={values.auto_generate_session_titles} onChange={(checked) => setValues({ ...values, auto_generate_session_titles: checked })} />
          <small>Generate a short title before the first LLM response in a new default-titled session.</small>
        </label>
        <InstructionField
          label="Session title prompt"
          description="Prompt used for automatic session title generation. Available variables: {user_input}."
          value={values.session_title_prompt}
          isDefault={values.session_title_prompt === values.session_title_prompt_default}
          onChange={(value) => setInstruction('session_title_prompt', value)}
          onReset={() => resetInstruction('session_title_prompt')}
        />
        <div className="settings-detail-grid">
          <NumberField label="Session title max input chars" value={values.session_title_max_input_chars} min={100} max={10000} onChange={(value) => setNumber('session_title_max_input_chars', value)} />
        </div>
      </div>
      <div className="detail-section">
        <div className="detail-section-heading">
          <h3>Context Rendering</h3>
        </div>
        <InstructionField
          label="Group transcript system instruction"
          description="Instruction appended when a session uses Group transcript mode. It tells the current agent how to read speaker labels and reply as itself."
          value={values.group_transcript_system_instruction ?? values.group_transcript_system_instruction_effective}
          isDefault={values.group_transcript_system_instruction === null}
          onChange={(value) => setInstruction('group_transcript_system_instruction', value)}
          onReset={() => resetInstruction('group_transcript_system_instruction')}
        />
        <InstructionField
          label="Command result context instruction"
          description="Instruction used when slash command results are included in LLM context. It should tell the model to treat command output as data, not instructions."
          value={values.command_result_context_instruction ?? values.command_result_context_instruction_effective}
          isDefault={values.command_result_context_instruction === null}
          onChange={(value) => setInstruction('command_result_context_instruction', value)}
          onReset={() => resetInstruction('command_result_context_instruction')}
        />
      </div>
    </>
  );
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
    session_title_prompt: values.session_title_prompt,
    session_title_max_input_chars: values.session_title_max_input_chars,
    group_transcript_system_instruction: values.group_transcript_system_instruction,
    command_result_context_instruction: values.command_result_context_instruction,
  };
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
  return (
    <label className="config-field settings-config-field">
      <span>
        {label}
        <button className="settings-secondary-button" type="button" onClick={onReset} disabled={isDefault}>
          Reset to default
        </button>
      </span>
      <textarea rows={6} value={value} onChange={(event) => onChange(event.currentTarget.value)} />
      <small>
        {description} {isDefault ? 'Using the default value.' : 'Using a saved override.'}
      </small>
    </label>
  );
}

function NumberField({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (value: string) => void }) {
  return (
    <label className="config-field settings-config-field">
      <span>{label}</span>
      <input type="number" min={min} max={max} value={value} onChange={(event) => onChange(event.currentTarget.value)} />
    </label>
  );
}

function DataDetail({ health, onDirtyChange }: { health?: HealthDetails; onDirtyChange: (dirty: boolean) => void }) {
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
            <h2>Data</h2>
            <p>SQLite local storage and attachment maintenance.</p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {saved ? <span className="settings-badge success">Saved</span> : null}
          {dirty ? (
            <button className="settings-primary-button" type="button" onClick={saveSettings}>
              <Save size={14} />
              Save
            </button>
          ) : null}
        </div>
      </header>
      <div className="settings-detail-body">
        {localError ? <SettingsApiError error={localError} /> : null}
        <div className="detail-section">
          <div className="detail-section-heading">
            <h3>Event log</h3>
          </div>
          <label className="config-field settings-config-field boolean-field">
            <span>Persist streaming message deltas</span>
            <ToggleSwitch checked={persistDeltas} onChange={setPersistDeltas} />
            <small>
              Store every streaming message_delta event in the local database for debugging. Disabled by default to keep the database smaller. Final
              messages, run steps, errors, and warnings are still stored.
            </small>
          </label>
        </div>
        <div className="detail-section">
          <div className="detail-section-heading">
            <h3>Database</h3>
          </div>
          <dl className="settings-definition-grid">
            <Metric label="Status" value={stats?.database.status || health?.database?.status || 'Unavailable'} />
            <Metric label="Schema version" value={stats?.database.schema_version || health?.schema_version || 'Unavailable'} />
            <Metric label="Database path" value={stats?.database.path || 'Unavailable'} wide />
            <Metric label="Database size" value={formatBytes(stats?.database.size_bytes || 0)} />
          </dl>
        </div>
        <div className="detail-section">
          <div className="detail-section-heading">
            <h3>Attachments</h3>
          </div>
          <dl className="settings-definition-grid">
            <Metric label="Directory" value={stats?.attachments.directory || 'Unavailable'} wide />
            <Metric label="Attachment count" value={String(stats?.attachments.count ?? 0)} />
            <Metric label="Total size" value={formatBytes(stats?.attachments.total_size_bytes || 0)} />
            <Metric label="Orphan count" value={String(orphanCount)} />
            <Metric label="Orphan size" value={formatBytes(stats?.attachments.orphan_size_bytes || 0)} />
          </dl>
        </div>
        <div className="detail-section">
          <div className="detail-section-heading">
            <h3>Maintenance</h3>
          </div>
          <div className="settings-button-row">
            <button className="settings-secondary-button" type="button" onClick={refresh} disabled={Boolean(busy)}>
              <RefreshCw size={14} />
              Refresh stats
            </button>
            <button className="settings-secondary-button" type="button" onClick={scan} disabled={Boolean(busy)}>
              <Search size={14} />
              Scan orphan attachments
            </button>
            <button className="settings-secondary-button danger" type="button" onClick={clean} disabled={Boolean(busy) || orphanCount === 0}>
              <Trash2 size={14} />
              {confirmClean ? 'Confirm clean' : 'Clean orphan attachments'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function DiagnosticsDetail() {
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
            <h2>Diagnostics</h2>
            <p>Local runtime health and configuration readiness.</p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {lastRefreshed ? <span className="settings-muted-text">Last refreshed {lastRefreshed}</span> : null}
          <button className="settings-secondary-button" type="button" onClick={refresh} disabled={busy}>
            <RefreshCw size={14} />
            {busy ? 'Refreshing...' : 'Refresh diagnostics'}
          </button>
        </div>
      </header>
      <div className="settings-detail-body">
        {localError ? <SettingsApiError error={localError} /> : null}
        {!diagnostics ? (
          <EmptyDetail title="Diagnostics" message={busy ? 'Loading diagnostics.' : 'Diagnostics unavailable.'} />
        ) : (
          <>
            <div className="settings-diagnostics-grid">
              <DiagnosticsCard title="System">
                <Metric label="Backend status" value={diagnostics.backend.status} />
                <Metric label="Version" value={diagnostics.backend.version || 'unknown'} />
                <Metric label="Python" value={diagnostics.backend.python_version || 'unknown'} />
                <Metric label="Uptime" value={formatDuration(diagnostics.backend.uptime_seconds || 0)} />
              </DiagnosticsCard>
              <DiagnosticsCard title="Database">
                <Metric label="Status" value={diagnostics.database.status} />
                <Metric label="Schema version" value={diagnostics.database.schema_version || 'unknown'} />
                <Metric label="DB size" value={formatBytes(diagnostics.database.size_bytes || 0)} />
              </DiagnosticsCard>
              <DiagnosticsCard title="Attachments">
                <Metric label="Status" value={diagnostics.attachments.status} />
                <Metric label="Count" value={String(diagnostics.attachments.count ?? 0)} />
                <Metric label="Total size" value={formatBytes(diagnostics.attachments.total_size_bytes || 0)} />
                <Metric label="Writable" value={diagnostics.attachments.writable ? 'Yes' : 'No'} />
              </DiagnosticsCard>
              <DiagnosticsCard title="Realtime">
                <Metric label="EventBus subscribers" value={String(diagnostics.event_bus.subscriber_count ?? 0)} />
                <Metric label="WebSocket connections" value={String(diagnostics.event_bus.active_websocket_connections ?? 0)} />
                <Metric label="Active runs" value={String(diagnostics.runs.active_count)} />
                <Metric label="Active tasks" value={String(diagnostics.runs.active_task_count ?? 0)} />
              </DiagnosticsCard>
              <DiagnosticsCard title="LLM">
                <Metric label="Profiles" value={`${diagnostics.llm.profiles_enabled} / ${diagnostics.llm.profiles_total} enabled`} />
                <Metric label="Resolved model" value={diagnostics.llm.default_resolved?.model_id || 'Not selected'} />
                <Metric label="Base URL" value={diagnostics.llm.default_resolved?.base_url || 'Unavailable'} />
                <Metric label="API key set" value={diagnostics.llm.default_resolved?.api_key_set ? 'Yes' : 'No'} />
              </DiagnosticsCard>
              <DiagnosticsCard title="Capabilities">
                <Metric label="File" value={`${diagnostics.capabilities.file.enabled ? 'Enabled' : 'Disabled'} / ${diagnostics.capabilities.file.status}`} />
                <Metric label="Allowed dirs" value={String(diagnostics.capabilities.file.allowed_directories_count ?? 0)} />
                <Metric label="/read-file" value={diagnostics.capabilities.file.read_file_enabled ? 'Enabled' : 'Disabled'} />
                <Metric label="/read-image" value={diagnostics.capabilities.file.read_image_enabled ? 'Enabled' : 'Disabled'} />
                <Metric label="Max text read" value={`${diagnostics.capabilities.file.max_local_text_read_size_mb ?? 0} MB`} />
                <Metric label="Max image read" value={`${diagnostics.capabilities.file.max_local_image_read_size_mb ?? 0} MB`} />
                <Metric label="HTTP" value={`${diagnostics.capabilities.http.enabled ? 'Enabled' : 'Disabled'} / ${diagnostics.capabilities.http.status}`} />
                <Metric label="HTTP GET" value={diagnostics.capabilities.http.http_get_enabled ? 'Enabled' : 'Disabled'} />
                <Metric label="Fetch image" value={diagnostics.capabilities.http.fetch_image_enabled ? 'Enabled' : 'Disabled'} />
                <Metric label="Max text response" value={`${diagnostics.capabilities.http.max_text_response_size_mb ?? 0} MB`} />
                <Metric label="Max image response" value={`${diagnostics.capabilities.http.max_image_response_size_mb ?? 0} MB`} />
                <Metric label="Redirects" value={diagnostics.capabilities.http.allow_redirects ? 'Allowed' : 'Disabled'} />
              </DiagnosticsCard>
            </div>
            <div className="detail-section">
              <div className="detail-section-heading">
                <h3>Recent failures</h3>
              </div>
              {diagnostics.runs.recent_failures.length ? (
                <div className="settings-table-wrap">
                  <table className="settings-table">
                    <thead>
                      <tr>
                        <th>Time</th>
                        <th>Target</th>
                        <th>Error</th>
                        <th>Message</th>
                      </tr>
                    </thead>
                    <tbody>
                      {diagnostics.runs.recent_failures.map((failure) => (
                        <tr key={failure.run_id}>
                          <td>{formatDateTime(failure.created_at)}</td>
                          <td>{failure.agent_id || failure.command_name || 'run'}</td>
                          <td>{failure.error_code}</td>
                          <td>{failure.message || 'No error message.'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="settings-empty-state compact">No recent failed runs.</div>
              )}
            </div>
            <div className="detail-section">
              <div className="detail-section-heading">
                <h3>Warnings</h3>
              </div>
              {diagnostics.warnings.length ? (
                <ul className="settings-warning-list">
                  {diagnostics.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              ) : (
                <div className="settings-empty-state compact">No warnings.</div>
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

function Metric({ label, value, wide }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={wide ? 'wide' : ''}>
      <dt>{label}</dt>
      <dd title={value}>{value}</dd>
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
  if (section === 'developer') {
    return (
      <div className="settings-placeholder">
        <h2>Developer</h2>
        <p>Agent development docs and utilities:</p>
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
        <h2>About</h2>
        <dl className="settings-definition-grid">
          <div>
            <dt>Version</dt>
            <dd>0.1.0-alpha</dd>
          </div>
          <div>
            <dt>Project status</dt>
            <dd>Technical Alpha</dd>
          </div>
        </dl>
      </div>
    );
  }
  return <EmptyDetail title="Settings" message="This settings section will be added later." />;
}

function EmptyDetail({ title, message }: { title: string; message: string }) {
  return (
    <div className="settings-placeholder">
      <h2>{title}</h2>
      <p>{message}</p>
    </div>
  );
}
