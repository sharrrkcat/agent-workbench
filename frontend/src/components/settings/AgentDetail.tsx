import { Save } from 'lucide-react';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { Agent, AgentAction, AgentConfig, ContextPolicy, ModelLifecyclePolicy } from '../../types';
import { AgentAvatar } from '../AgentAvatar';
import { ConfigForm } from './ConfigForm';
import { DetailTabs } from './DetailTabs';
import { ManifestViewer } from './ManifestViewer';
import { ToggleSwitch } from './ToggleSwitch';
import { buildUserConfig, displayValue, initialConfigValues, isConfigDirty, type ConfigValues } from './configUtils';

const baseTabs = [
  { id: 'overview', label: 'Overview' },
  { id: 'actions', label: 'Actions' },
  { id: 'config', label: 'Config' },
  { id: 'runtime', label: 'Runtime' },
  { id: 'manifest', label: 'Manifest' },
];

export function AgentDetail({
  config,
  agent,
  activeTab,
  onTabChange,
  onDirtyChange,
}: {
  config: AgentConfig;
  agent?: Agent;
  activeTab: string;
  onTabChange: (tab: string) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { updateAgentConfig, savingConfigId } = useWorkbenchStore();
  const [enabled, setEnabled] = useState(config.enabled);
  const [values, setValues] = useState<ConfigValues>(() => initialConfigValues(config));
  const [localError, setLocalError] = useState('');
  const isSaving = savingConfigId === `agent:${config.agent_id}`;
  const dirty = isConfigDirty(config, enabled, values);
  const summary = config.manifest_summary;
  const name = summary.name || agent?.name || config.agent_id;
  const hasActions = Boolean(agent?.actions?.length);
  const hasConfigFields = Boolean(config.config_schema?.length);
  const hasRuntime = Boolean(agent?.context_policy || agent?.model_lifecycle || agent?.llm || agent?.model || agent?.type === 'script');
  const manifest = useMemo(() => ({ agent, config }), [agent, config]);
  const tabs = useMemo(
    () =>
      baseTabs.map((tab) => ({
        ...tab,
        enabled:
          tab.id === 'overview' ||
          (tab.id === 'actions' && hasActions) ||
          (tab.id === 'config' && hasConfigFields) ||
          (tab.id === 'runtime' && hasRuntime) ||
          tab.id === 'manifest',
      })),
    [hasActions, hasConfigFields, hasRuntime],
  );
  const normalizedActiveTab = tabs.some((tab) => tab.id === activeTab && tab.enabled !== false) ? activeTab : 'overview';

  useEffect(() => {
    setEnabled(config.enabled);
    setValues(initialConfigValues(config));
    setLocalError('');
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
      setLocalError('');
      await updateAgentConfig(config.agent_id, { enabled, user_config: buildUserConfig(config.config_schema || [], values) });
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : 'Failed to save agent config.');
    }
  }

  return (
    <form className="settings-detail-form" onSubmit={save}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <AgentAvatar agent={agent || summary} label={name} className="settings-detail-avatar" iconSize={18} />
          <div>
            <h2>{name}</h2>
            <p>
              <code>{config.agent_id}</code>
              <span>{summary.type || agent?.type || 'agent'}</span>
            </p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {dirty ? (
            <button className="settings-primary-button" type="submit" disabled={isSaving}>
              <Save size={14} />
              {isSaving ? 'Saving...' : 'Save'}
            </button>
          ) : null}
          <ToggleSwitch checked={enabled} onChange={setEnabled} disabled={isSaving} />
        </div>
      </header>

      <DetailTabs tabs={tabs} activeTab={normalizedActiveTab} onChange={onTabChange} />
      <div className="settings-detail-body">
        {localError ? <p className="settings-error-text">{localError}</p> : null}
        {normalizedActiveTab === 'actions' ? <ActionsTab actions={agent?.actions || []} /> : null}
        {normalizedActiveTab === 'config' ? (
          <ConfigForm
            fields={config.config_schema || []}
            values={values}
            onChange={setValues}
            emptyMessage="This agent has no configurable fields."
          />
        ) : null}
        {normalizedActiveTab === 'runtime' ? <RuntimeTab agent={agent} /> : null}
        {normalizedActiveTab === 'manifest' ? <ManifestViewer value={manifest} /> : null}
        {normalizedActiveTab === 'overview' ? <OverviewTab config={config} agent={agent} /> : null}
      </div>
    </form>
  );
}

function OverviewTab({ config, agent }: { config: AgentConfig; agent?: Agent }) {
  const summary = config.manifest_summary;
  return (
    <div className="settings-detail-grid">
      <InfoRow label="Description" value={summary.description || agent?.description || 'No description.'} wide />
      <InfoRow label="Type" value={summary.type || agent?.type || 'agent'} />
      <div className="settings-info-row">
        <span>Capabilities</span>
        <div className="settings-chip-row">
          {agent?.capabilities?.length ? (
            agent.capabilities.map((capability) => <span key={capability}>{capability}</span>)
          ) : (
            <small>No declared capabilities</small>
          )}
        </div>
      </div>
      <InfoRow label="Context policy" value={summarizeContextPolicy(agent?.context_policy)} />
      <InfoRow label="Model lifecycle" value={summarizeLifecycle(agent?.model_lifecycle)} />
      <InfoRow label="LLM" value={summarizeLlm(agent)} />
    </div>
  );
}

function ActionsTab({ actions }: { actions: AgentAction[] }) {
  if (!actions.length) {
    return <div className="settings-empty-state">This agent does not declare actions.</div>;
  }
  return (
    <div className="settings-table-wrap">
      <table className="settings-table">
        <thead>
          <tr>
            <th>Action</th>
            <th>Label</th>
            <th>Description</th>
            <th>Instruction</th>
            <th>Callable</th>
            <th>Context</th>
          </tr>
        </thead>
        <tbody>
          {actions.map((action) => (
            <tr key={action.id}>
              <td>
                <code>{action.id}</code>
              </td>
              <td>{action.label || (action.id === 'default' ? 'Default' : 'Unset')}</td>
              <td>{action.description || 'None'}</td>
              <td>{action.instruction || 'None'}</td>
              <td>{action.callable ? 'Yes' : 'No'}</td>
              <td>{summarizeContextPolicy(action.context_policy)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RuntimeTab({ agent }: { agent?: Agent }) {
  return (
    <div className="settings-runtime-stack">
      <section className="detail-section">
        <h3>Context policy</h3>
        <PolicyGrid policy={agent?.context_policy} />
      </section>
      <section className="detail-section">
        <h3>Model lifecycle</h3>
        <dl className="settings-definition-grid">
          <div>
            <dt>Load</dt>
            <dd>{agent?.model_lifecycle?.load || 'Unset'}</dd>
          </div>
          <div>
            <dt>Unload</dt>
            <dd>{agent?.model_lifecycle?.unload || 'Unset'}</dd>
          </div>
          <div>
            <dt>Unload failure</dt>
            <dd>{agent?.model_lifecycle?.unload_failure || 'Unset'}</dd>
          </div>
        </dl>
      </section>
      <section className="detail-section">
        <h3>LLM routing</h3>
        <LlmRuntimeSummary agent={agent} />
      </section>
      <section className="detail-section">
        <h3>Legacy model</h3>
        {agent?.model ? <ManifestViewer value={agent.model} /> : <div className="settings-empty-state">Uses global LLM fallback.</div>}
      </section>
      {agent?.type === 'script' ? (
        <p className="settings-warning-text">Script Agents are trusted local Python code and are not sandboxed.</p>
      ) : null}
    </div>
  );
}

function PolicyGrid({ policy }: { policy?: ContextPolicy | null }) {
  return (
    <dl className="settings-definition-grid">
      <div>
        <dt>Mode</dt>
        <dd>{policy?.mode || 'Unset'}</dd>
      </div>
      <div>
        <dt>Max messages</dt>
        <dd>{displayValue(policy?.max_messages)}</dd>
      </div>
      <div>
        <dt>Max chars</dt>
        <dd>{displayValue(policy?.max_chars)}</dd>
      </div>
      <div>
        <dt>Original user message</dt>
        <dd>{displayValue(policy?.include_original_user_message)}</dd>
      </div>
      <div>
        <dt>Last agent message</dt>
        <dd>{displayValue(policy?.include_last_agent_message)}</dd>
      </div>
    </dl>
  );
}

function LlmRuntimeSummary({ agent }: { agent?: Agent }) {
  if (agent?.llm?.profile) {
    const overrides = ['temperature', 'top_p', 'top_k', 'max_tokens']
      .map((key) => [key, agent.llm?.[key as keyof NonNullable<Agent['llm']>]])
      .filter(([, value]) => value !== undefined && value !== null && value !== '');
    return (
      <dl className="settings-definition-grid">
        <div>
          <dt>LLM profile</dt>
          <dd>{agent.llm.profile}</dd>
        </div>
        <div>
          <dt>Session override</dt>
          <dd>{agent.llm.allow_session_override === false ? 'no' : 'yes'}</dd>
        </div>
        <div>
          <dt>Overrides</dt>
          <dd>{overrides.length ? overrides.map(([key, value]) => `${key}: ${value}`).join(', ') : 'None'}</dd>
        </div>
      </dl>
    );
  }
  if (agent?.model) {
    const model = String(agent.model.model || agent.model.model_id || 'unset');
    const provider = String(agent.model.provider || 'openai_compatible');
    const baseUrl = String(agent.model.base_url || 'unset');
    return (
      <dl className="settings-definition-grid">
        <div>
          <dt>Legacy model</dt>
          <dd>{model}</dd>
        </div>
        <div>
          <dt>Provider</dt>
          <dd>{provider}</dd>
        </div>
        <div>
          <dt>Base URL</dt>
          <dd>{baseUrl}</dd>
        </div>
      </dl>
    );
  }
  return <div className="settings-empty-state">Uses global LLM fallback.</div>;
}

function InfoRow({ label, value, wide = false }: { label: string; value: unknown; wide?: boolean }) {
  return (
    <div className={`settings-info-row ${wide ? 'wide' : ''}`}>
      <span>{label}</span>
      <strong>{displayValue(value)}</strong>
    </div>
  );
}

function summarizeContextPolicy(policy?: ContextPolicy | null): string {
  if (!policy) return 'Inherited/default';
  const parts: string[] = [policy.mode];
  if (policy.max_messages) parts.push(`${policy.max_messages} messages`);
  if (policy.max_chars) parts.push(`${policy.max_chars} chars`);
  return parts.join(' · ');
}

function summarizeLlm(agent?: Agent): string {
  if (agent?.llm?.profile) return `LLM profile: ${agent.llm.profile}`;
  if (agent?.model) return `Legacy model: ${String(agent.model.model || agent.model.model_id || 'unset')}`;
  return 'Uses global LLM fallback';
}

function summarizeLifecycle(policy?: ModelLifecyclePolicy): string {
  if (!policy) return 'Unset';
  return `${policy.load} · unload ${policy.unload} · failure ${policy.unload_failure}`;
}
