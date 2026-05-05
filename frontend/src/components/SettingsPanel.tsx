import { FormEvent, useEffect, useState } from 'react';
import { Settings } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { AgentConfig, CapabilityConfig } from '../types';

type ConfigKind = 'agent' | 'capability';

export function SettingsPanel() {
  const { agentConfigs, capabilityConfigs } = useWorkbenchStore();

  return (
    <section className="settings-panel">
      <div className="panel-title">
        <Settings size={15} />
        Settings
      </div>
      <div className="settings-section">
        <h2>Agents</h2>
        {agentConfigs.map((config) => (
          <ConfigEditor key={config.agent_id} kind="agent" config={config} id={config.agent_id} name={config.manifest_summary.name} />
        ))}
      </div>
      <div className="settings-section">
        <h2>Capabilities</h2>
        {capabilityConfigs.map((config) => (
          <ConfigEditor
            key={config.capability_id}
            kind="capability"
            config={config}
            id={config.capability_id}
            name={config.manifest_summary.name}
          />
        ))}
      </div>
    </section>
  );
}

function ConfigEditor({
  kind,
  config,
  id,
  name,
}: {
  kind: ConfigKind;
  config: AgentConfig | CapabilityConfig;
  id: string;
  name: string;
}) {
  const { updateAgentConfig, updateCapabilityConfig, loading } = useWorkbenchStore();
  const [enabled, setEnabled] = useState(config.enabled);
  const [jsonText, setJsonText] = useState(formatConfig(config.user_config));
  const [jsonError, setJsonError] = useState('');

  useEffect(() => {
    setEnabled(config.enabled);
    setJsonText(formatConfig(config.user_config));
    setJsonError('');
  }, [config.enabled, config.user_config]);

  async function save(event: FormEvent) {
    event.preventDefault();
    let parsed: unknown;
    try {
      parsed = JSON.parse(jsonText || '{}');
    } catch {
      setJsonError('JSON is invalid.');
      return;
    }
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
      setJsonError('user_config must be a JSON object.');
      return;
    }
    setJsonError('');
    if (kind === 'agent') {
      await updateAgentConfig(id, { enabled, user_config: parsed as Record<string, unknown> });
    } else {
      await updateCapabilityConfig(id, { enabled, user_config: parsed as Record<string, unknown> });
    }
  }

  return (
    <form className="config-row" onSubmit={save}>
      <label className="config-toggle">
        <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
        <span>{name || id}</span>
        <small>{id}</small>
      </label>
      <textarea value={jsonText} onChange={(event) => setJsonText(event.target.value)} rows={4} spellCheck={false} />
      {jsonError ? <p>{jsonError}</p> : null}
      <button type="submit" disabled={loading}>
        Save
      </button>
    </form>
  );
}

function formatConfig(config: Record<string, unknown>) {
  return JSON.stringify(config || {}, null, 2);
}
