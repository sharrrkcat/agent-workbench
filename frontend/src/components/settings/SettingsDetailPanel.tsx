import { Database, Info, Save, Settings } from 'lucide-react';
import { FormEvent, useEffect, useState } from 'react';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { Agent, AgentConfig, CapabilityConfig, Command, HealthDetails } from '../../types';
import { AgentDetail } from './AgentDetail';
import { CapabilityDetail } from './CapabilityDetail';
import { LlmSettingsPanel } from './LlmSettingsPanel';
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
        {selectedCapabilityConfig ? <LlmDetail config={selectedCapabilityConfig} onDirtyChange={onDirtyChange} /> : null}
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
        <LlmSettingsPanel config={config} values={values} onValuesChange={setValues} onBusyChange={setLlmBusy} />
      </div>
    </form>
  );
}

function PlaceholderDetail({ section, health }: { section: SettingsSection; health?: HealthDetails }) {
  if (section === 'general') {
    return <EmptyDetail title="General" message="General settings will be added later." />;
  }
  if (section === 'data') {
    return (
      <div className="settings-placeholder">
        <Database size={22} />
        <h2>Data</h2>
        <dl className="settings-definition-grid">
          <div>
            <dt>Database</dt>
            <dd>{health?.database?.status || 'Unavailable'}</dd>
          </div>
          <div>
            <dt>Schema version</dt>
            <dd>{health?.schema_version || 'Unavailable'}</dd>
          </div>
          <div>
            <dt>Persistence</dt>
            <dd>SQLite local storage</dd>
          </div>
        </dl>
      </div>
    );
  }
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
