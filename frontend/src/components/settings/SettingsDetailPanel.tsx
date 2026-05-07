import { Database, Info, RefreshCw, Save, Search, Settings, Trash2 } from 'lucide-react';
import { FormEvent, useEffect, useState } from 'react';
import { api } from '../../api/client';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { Agent, AgentConfig, CapabilityConfig, Command, GeneralSettings, HealthDetails, LlmProfile, StorageStats } from '../../types';
import { AgentDetail } from './AgentDetail';
import { CapabilityDetail } from './CapabilityDetail';
import { LlmProfileDetail, LlmSettingsPanel } from './LlmSettingsPanel';
import { SettingsApiError, toSettingsError, type SettingsErrorValue } from './SettingsApiError';
import { ToggleSwitch } from './ToggleSwitch';
import { buildUserConfig, displayValue, initialConfigValues, isConfigDirty, type ConfigValues } from './configUtils';
import type { SettingsSection } from './SettingsNav';

export function SettingsDetailPanel({
  section,
  selectedAgent,
  selectedAgentConfig,
  selectedCapabilityConfig,
  commands,
  health,
  llmProfiles = [],
  selectedLlmItemId = 'global',
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
  selectedLlmItemId?: string;
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
        {selectedLlmItemId === 'global' ? (
          selectedCapabilityConfig ? <LlmDetail config={selectedCapabilityConfig} onDirtyChange={onDirtyChange} /> : null
        ) : (
          <LlmProfileDetail
            profiles={llmProfiles}
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
        <GeneralDetail onDirtyChange={onDirtyChange} />
      </section>
    );
  }

  if (section === 'data') {
    return (
      <section className="settings-detail-panel">
        <DataDetail health={health} />
      </section>
    );
  }

  return (
    <section className="settings-detail-panel">
      <PlaceholderDetail section={section} health={health} />
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

function GeneralDetail({ onDirtyChange }: { onDirtyChange: (dirty: boolean) => void }) {
  const { generalSettings, refreshGeneralSettings, updateGeneralSettings } = useWorkbenchStore();
  const [values, setValues] = useState<GeneralSettings | null>(generalSettings || null);
  const [localError, setLocalError] = useState<SettingsErrorValue | null>(null);
  const [saved, setSaved] = useState(false);
  const dirty = Boolean(values && generalSettings && JSON.stringify(values) !== JSON.stringify(generalSettings));

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
      await updateGeneralSettings(values);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 1400);
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to save general settings.'));
    }
  }

  function setNumber(key: keyof GeneralSettings, value: string) {
    setValues((current) => (current ? { ...current, [key]: Number(value) } : current));
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
            <h2>General</h2>
            <p>Upload limits are enforced by the backend.</p>
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
      </div>
    </form>
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

function DataDetail({ health }: { health?: HealthDetails }) {
  const [stats, setStats] = useState<StorageStats | null>(null);
  const [busy, setBusy] = useState('');
  const [localError, setLocalError] = useState<SettingsErrorValue | null>(null);
  const [confirmClean, setConfirmClean] = useState(false);

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
  }, []);

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
      </header>
      <div className="settings-detail-body">
        {localError ? <SettingsApiError error={localError} /> : null}
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

function PlaceholderDetail({ section, health }: { section: SettingsSection; health?: HealthDetails }) {
  if (section === 'diagnostics') {
    return (
      <div className="settings-placeholder">
        <Info size={22} />
        <h2>Diagnostics</h2>
        <dl className="settings-definition-grid">
          <div>
            <dt>Backend</dt>
            <dd>{health?.status || 'Unavailable'}</dd>
          </div>
          <div>
            <dt>Schema version</dt>
            <dd>{health?.schema_version || 'Unavailable'}</dd>
          </div>
          <div>
            <dt>Agents</dt>
            <dd>{displayValue(health?.registries?.agents)}</dd>
          </div>
          <div>
            <dt>Capabilities</dt>
            <dd>{displayValue(health?.registries?.capabilities)}</dd>
          </div>
          <div>
            <dt>Commands</dt>
            <dd>{displayValue(health?.registries?.commands)}</dd>
          </div>
        </dl>
      </div>
    );
  }
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
