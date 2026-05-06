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

const tabs = [
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

  useEffect(() => {
    setEnabled(config.enabled);
    setValues(initialConfigValues(config));
    setLocalError(null);
    setHealthBusy(false);
  }, [config]);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  async function save(event: FormEvent) {
    event.preventDefault();
    try {
      setLocalError(null);
      await updateCapabilityConfig(config.capability_id, { enabled, user_config: buildUserConfig(config.config_schema || [], values) });
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to save capability config.'));
    }
  }

  const capabilityCommands = commands.filter((command) => command.capability_id === config.capability_id);
  const manifestCommands = summary.commands || [];
  const visibleCommands = capabilityCommands.length ? capabilityCommands : manifestCommands;
  const manifest = useMemo(() => ({ config, commands: visibleCommands }), [config, visibleCommands]);

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

      <DetailTabs tabs={tabs} activeTab={tabs.some((tab) => tab.id === activeTab) ? activeTab : 'overview'} onChange={onTabChange} />
      <div className="settings-detail-body">
        {localError ? <SettingsApiError error={localError} /> : null}
        {activeTab === 'commands' ? <CommandsTab commands={visibleCommands} capabilityEnabled={enabled} /> : null}
        {activeTab === 'config' ? (
          <ConfigForm
            fields={config.config_schema || []}
            values={values}
            onChange={setValues}
            emptyMessage="This capability has no configurable fields."
          />
        ) : null}
        {activeTab === 'health' ? (
          config.capability_id === 'llm' ? (
            <LlmSettingsPanel config={config} values={values} onValuesChange={setValues} showConfig={false} onBusyChange={setHealthBusy} />
          ) : (
            <div className="settings-empty-state">No health checks available for this capability.</div>
          )
        ) : null}
        {activeTab === 'manifest' ? <ManifestViewer value={manifest} /> : null}
        {activeTab === 'overview' || !tabs.some((tab) => tab.id === activeTab) ? (
          <OverviewTab config={config} commandCount={visibleCommands.length} />
        ) : null}
      </div>
    </form>
  );
}

function OverviewTab({ config, commandCount }: { config: CapabilityConfig; commandCount: number }) {
  const summary = config.manifest_summary;
  const configFieldCount = config.config_schema?.length ?? 0;
  return (
    <div className="settings-detail-grid">
      <InfoRow label="Name" value={summary.name || config.capability_id} />
      <InfoRow label="ID" value={config.capability_id} />
      <InfoRow label="Description" value={summary.description} />
      <InfoRow label="Version" value={(summary as { version?: string }).version} />
      <InfoRow label="Entry / runtime" value={config.capability_id === 'llm' ? 'OpenAI-compatible LLM runtime' : 'Local Python capability'} />
      <InfoRow label="Enabled" value={config.enabled} />
      <InfoRow label="Exposed commands" value={commandCount} />
      <InfoRow label="Config fields" value={configFieldCount} />
    </div>
  );
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

function InfoRow({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="settings-info-row">
      <span>{label}</span>
      <strong>{displayValue(value)}</strong>
    </div>
  );
}
