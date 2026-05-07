import { Boxes, Save } from 'lucide-react';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { CapabilityConfig, Command } from '../../types';
import { ConfigForm } from './ConfigForm';
import { DetailTabs } from './DetailTabs';
import { LlmSettingsPanel } from './LlmSettingsPanel';
import { ManifestViewer } from './ManifestViewer';
import { SettingsApiError, toSettingsError, type SettingsErrorValue } from './SettingsApiError';
import { ToggleSwitch } from './ToggleSwitch';
import { buildUserConfig, displayValue, initialConfigValues, initials, isConfigDirty, type ConfigValues } from './configUtils';

const baseTabs = [
  { id: 'overview', label: 'Overview' },
  { id: 'commands', label: 'Commands' },
  { id: 'config', label: 'Config' },
  { id: 'health', label: 'Health' },
  { id: 'manifest', label: 'Manifest' },
];

export function CapabilityDetail({
  config,
  commands,
  activeTab,
  onTabChange,
  onDirtyChange,
}: {
  config: CapabilityConfig;
  commands: Command[];
  activeTab: string;
  onTabChange: (tab: string) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { updateCapabilityConfig, savingConfigId, testingLlm } = useWorkbenchStore();
  const [enabled, setEnabled] = useState(config.enabled);
  const [values, setValues] = useState<ConfigValues>(() => initialConfigValues(config));
  const [localError, setLocalError] = useState<SettingsErrorValue | null>(null);
  const [healthBusy, setHealthBusy] = useState(false);
  const isSaving = savingConfigId === `capability:${config.capability_id}`;
  const saveDisabled = isSaving || (config.capability_id === 'llm' && (testingLlm || healthBusy));
  const dirty = isConfigDirty(config, enabled, values);
  const summary = config.manifest_summary;
  const name = summary.name || config.capability_id;
  const capabilityCommands = commands.filter((command) => command.capability_id === config.capability_id);
  const manifestCommands = summary.commands || [];
  const visibleCommands = capabilityCommands.length ? capabilityCommands : manifestCommands;
  const hasCommands = Boolean(visibleCommands.length);
  const hasConfigFields = Boolean(config.config_schema?.length);
  const hasHealth = config.capability_id === 'llm';
  const manifest = useMemo(() => ({ config, commands: visibleCommands }), [config, visibleCommands]);
  const tabs = useMemo(
    () =>
      baseTabs.map((tab) => ({
        ...tab,
        enabled:
          tab.id === 'overview' ||
          (tab.id === 'commands' && hasCommands) ||
          (tab.id === 'config' && hasConfigFields) ||
          (tab.id === 'health' && hasHealth) ||
          tab.id === 'manifest',
      })),
    [hasCommands, hasConfigFields, hasHealth],
  );
  const normalizedActiveTab = tabs.some((tab) => tab.id === activeTab && tab.enabled !== false) ? activeTab : 'overview';

  useEffect(() => {
    setEnabled(config.enabled);
    setValues(initialConfigValues(config));
    setLocalError(null);
    setHealthBusy(false);
  }, [config]);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    if (activeTab !== normalizedActiveTab) {
      onTabChange(normalizedActiveTab);
    }
  }, [activeTab, normalizedActiveTab, onTabChange]);

  async function save(event: FormEvent) {
    event.preventDefault();
    try {
      setLocalError(null);
      await updateCapabilityConfig(config.capability_id, { enabled, user_config: buildUserConfig(config.config_schema || [], values) });
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to save capability config.'));
    }
  }

  return (
    <form className={`settings-detail-form ${enabled ? '' : 'disabled'}`} onSubmit={save}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">{initials(name) || <Boxes size={18} />}</div>
          <div>
            <h2>{name}</h2>
            <p>
              <code>{config.capability_id}</code>
              <span>capability</span>
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

      <DetailTabs tabs={tabs} activeTab={normalizedActiveTab} onChange={onTabChange} />
      <div className="settings-detail-body">
        {localError ? <SettingsApiError error={localError} /> : null}
        {normalizedActiveTab === 'commands' ? <CommandsTab commands={visibleCommands} capabilityEnabled={enabled} /> : null}
        {normalizedActiveTab === 'config' ? (
          <CapabilityConfigTab config={config} values={values} onChange={setValues} />
        ) : null}
        {normalizedActiveTab === 'health' ? (
          config.capability_id === 'llm' ? (
            <LlmSettingsPanel config={config} values={values} onValuesChange={setValues} showConfig={false} onBusyChange={setHealthBusy} />
          ) : (
            <div className="settings-empty-state">No health checks available for this capability.</div>
          )
        ) : null}
        {normalizedActiveTab === 'manifest' ? <ManifestViewer value={manifest} /> : null}
        {normalizedActiveTab === 'overview' ? (
          <OverviewTab config={config} commandCount={visibleCommands.length} />
        ) : null}
      </div>
    </form>
  );
}

function CapabilityConfigTab({
  config,
  values,
  onChange,
}: {
  config: CapabilityConfig;
  values: ConfigValues;
  onChange: (values: ConfigValues) => void;
}) {
  const fields = config.config_schema || [];
  if (config.capability_id === 'file') {
    return (
      <div className="settings-config-sections">
        <p className="settings-helper-text">
          File Capability settings apply only to <code>/read-file</code> and <code>/read-image</code>. General upload limits are configured in General.
        </p>
        <ConfigSection title="Permissions" fieldNames={['allowed_directories']} fields={fields} values={values} onChange={onChange} />
        <ConfigSection
          title="Read limits"
          fieldNames={['max_local_text_read_size_mb', 'max_local_image_read_size_mb', 'allowed_text_extensions']}
          fields={fields}
          values={values}
          onChange={onChange}
        />
        <ConfigSection title="Commands" fieldNames={['enable_read_file', 'enable_read_image']} fields={fields} values={values} onChange={onChange} />
      </div>
    );
  }
  if (config.capability_id === 'http') {
    return (
      <div className="settings-config-sections">
        <p className="settings-helper-text">
          HTTP settings apply only to <code>/http-get</code>, <code>/fetch-page</code>, and <code>/fetch-image</code>. They do not affect chat uploads.
        </p>
        <ConfigSection
          title="Network access"
          fieldNames={['enable_http_get', 'enable_fetch_image', 'allowed_schemes', 'timeout_seconds', 'allow_redirects', 'max_redirects']}
          fields={fields}
          values={values}
          onChange={onChange}
        />
        <ConfigSection
          title="Response limits"
          fieldNames={['max_text_response_size_mb', 'max_image_response_size_mb']}
          fields={fields}
          values={values}
          onChange={onChange}
        />
      </div>
    );
  }
  return (
    <ConfigForm
      fields={fields}
      values={values}
      onChange={onChange}
      emptyMessage="This capability has no configurable fields."
    />
  );
}

function ConfigSection({
  title,
  fieldNames,
  fields,
  values,
  onChange,
}: {
  title: string;
  fieldNames: string[];
  fields: CapabilityConfig['config_schema'];
  values: ConfigValues;
  onChange: (values: ConfigValues) => void;
}) {
  const sectionFields = fields.filter((field) => fieldNames.includes(field.name));
  if (!sectionFields.length) return null;
  return (
    <section className="settings-config-section">
      <h3>{title}</h3>
      <ConfigForm fields={sectionFields} values={values} onChange={onChange} emptyMessage="No configurable fields." />
    </section>
  );
}

function OverviewTab({ config, commandCount }: { config: CapabilityConfig; commandCount: number }) {
  const summary = config.manifest_summary;
  const configFieldCount = config.config_schema?.length ?? 0;
  const permissionHint = permissionHintText(summary.permissions);
  return (
    <div className="settings-detail-grid">
      <InfoRow label="Description" value={summary.description} wide />
      {permissionHint ? <InfoRow label="Permission hint" value={permissionHint} wide /> : null}
      <InfoRow label="Version" value={(summary as { version?: string }).version} />
      <InfoRow label="Exposed commands" value={commandCount} />
      <InfoRow label="Config fields" value={configFieldCount} />
      <InfoRow label="Runtime" value={config.capability_id === 'llm' ? 'OpenAI-compatible LLM runtime' : 'Local Python capability'} />
    </div>
  );
}

function permissionHintText(permissions: CapabilityConfig['manifest_summary']['permissions']): string {
  if (!permissions) return '';
  const hints: string[] = [];
  if (permissions.filesystem?.read) hints.push('Can read local files from configured allowed directories');
  if (permissions.network?.http) hints.push('Can make HTTP GET requests without private browser cookies');
  return hints.join('; ');
}

function CommandsTab({ commands, capabilityEnabled }: { commands: Command[]; capabilityEnabled: boolean }) {
  if (!commands.length) {
    return <div className="settings-empty-state">This capability does not expose slash commands.</div>;
  }
  return (
    <div className={`settings-table-wrap ${capabilityEnabled ? '' : 'disabled'}`}>
      <table className="settings-table">
        <thead>
          <tr>
            <th>Command</th>
            <th>Method</th>
            <th>Description</th>
            <th>Safe</th>
            <th>Confirm</th>
          </tr>
        </thead>
        <tbody>
          {commands.map((command) => (
            <tr key={command.name}>
              <td>
                <code>{command.name}</code>
              </td>
              <td>{command.method}</td>
              <td>{command.description || 'None'}</td>
              <td>
                <span className={`settings-badge ${command.safe ? 'success' : 'muted'}`}>{command.safe ? 'yes' : 'no'}</span>
              </td>
              <td>
                <span className={`settings-badge ${command.confirm ? 'warning' : 'muted'}`}>{command.confirm || 'no'}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InfoRow({ label, value, wide = false }: { label: string; value: unknown; wide?: boolean }) {
  return (
    <div className={`settings-info-row ${wide ? 'wide' : ''}`}>
      <span>{label}</span>
      <strong>{displayValue(value)}</strong>
    </div>
  );
}
