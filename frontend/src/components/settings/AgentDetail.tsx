import { RotateCcw, Save, Upload } from 'lucide-react';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { Agent, AgentAction, AgentConfig, AgentDisplayOverrides, AgentRuntimeOverrides, ContextPolicy, ModelLifecyclePolicy } from '../../types';
import { AgentAvatar } from '../AgentAvatar';
import { ConfigForm } from './ConfigForm';
import { DetailTabs } from './DetailTabs';
import { ManifestViewer } from './ManifestViewer';
import { ToggleSwitch } from './ToggleSwitch';
import { buildUserConfig, displayValue, initialConfigValues, isConfigDirty, type ConfigValues } from './configUtils';

const baseTabs = [
  { id: 'overview', label: 'Overview' },
  { id: 'overrides', label: 'Overrides' },
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
  const { llmProfiles, updateAgentConfig, resetAgentOverrides, writeAgentOverridesToManifest, savingConfigId } = useWorkbenchStore();
  const [enabled, setEnabled] = useState(config.enabled);
  const [values, setValues] = useState<ConfigValues>(() => initialConfigValues(config));
  const [displayDraft, setDisplayDraft] = useState<AgentDisplayOverrides>(() => ({ ...(config.display || config.overrides?.display || {}) }));
  const [runtimeDraft, setRuntimeDraft] = useState<AgentRuntimeOverrides>(() => ({ ...(config.runtime || config.overrides?.runtime || {}) }));
  const [localError, setLocalError] = useState('');
  const isSaving = savingConfigId === `agent:${config.agent_id}`;
  const dirty = isConfigDirty(config, enabled, values);
  const overridesDirty = JSON.stringify(displayDraft) !== JSON.stringify(config.display || config.overrides?.display || {}) ||
    JSON.stringify(runtimeDraft) !== JSON.stringify(config.runtime || config.overrides?.runtime || {});
  const hasSavedOverrides = Boolean(Object.keys(config.display || {}).length || Object.keys(config.runtime || {}).length);
  const summary = config.manifest_summary;
  const name = config.resolved?.display?.name || summary.name || agent?.name || config.agent_id;
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
          tab.id === 'overrides' ||
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
    setDisplayDraft({ ...(config.display || config.overrides?.display || {}) });
    setRuntimeDraft({ ...(config.runtime || config.overrides?.runtime || {}) });
    setLocalError('');
  }, [config]);

  useEffect(() => {
    onDirtyChange(dirty || overridesDirty);
  }, [dirty, overridesDirty, onDirtyChange]);

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

  async function saveOverrides() {
    try {
      setLocalError('');
      await updateAgentConfig(config.agent_id, {
        ...(dirty ? { enabled, user_config: buildUserConfig(config.config_schema || [], values) } : {}),
        display: normalizedDisplayDraft(displayDraft, config),
        runtime: normalizedRuntimeDraft(runtimeDraft, config),
      });
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : 'Failed to save agent overrides.');
    }
  }

  async function resetOverrides() {
    if (!window.confirm('Reset display and runtime overrides for this agent? Config tab values will be kept.')) return;
    try {
      setLocalError('');
      await resetAgentOverrides(config.agent_id);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : 'Failed to reset agent overrides.');
    }
  }

  async function writeManifest() {
    if (
      !window.confirm(
        `Write current overrides to agents/${config.agent_id}/agent.yaml?\n\nThis modifies the agent package file. Use this only when developing or customizing local agents. This may rewrite formatting/comments.`,
      )
    ) {
      return;
    }
    try {
      setLocalError('');
      if (overridesDirty) {
        await updateAgentConfig(config.agent_id, {
          display: normalizedDisplayDraft(displayDraft, config),
          runtime: normalizedRuntimeDraft(runtimeDraft, config),
        });
      }
      await writeAgentOverridesToManifest(config.agent_id);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : 'Failed to write agent manifest.');
    }
  }

  return (
    <form className="settings-detail-form" onSubmit={save}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <AgentAvatar agent={agent || { ...summary, ...config.resolved?.display }} label={name} className="settings-detail-avatar" iconSize={18} />
          <div>
            <h2>{name}</h2>
            <p>
              <code>{config.agent_id}</code>
              <span>{summary.type || agent?.type || 'agent'}</span>
            </p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {normalizedActiveTab === 'overrides' && (overridesDirty || dirty) ? (
            <button className="settings-primary-button" type="button" disabled={isSaving} onClick={saveOverrides}>
              <Save size={14} />
              {isSaving ? 'Saving...' : 'Save'}
            </button>
          ) : null}
          {normalizedActiveTab !== 'overrides' && dirty ? (
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
        {normalizedActiveTab === 'overrides' ? (
          <OverridesTab
            config={config}
            agent={agent}
            displayDraft={displayDraft}
            runtimeDraft={runtimeDraft}
            onDisplayChange={setDisplayDraft}
            onRuntimeChange={setRuntimeDraft}
            profiles={llmProfiles}
            saving={isSaving}
            dirty={overridesDirty}
            hasSavedOverrides={hasSavedOverrides}
            onReset={resetOverrides}
            onWriteManifest={writeManifest}
          />
        ) : null}
        {normalizedActiveTab === 'runtime' ? <RuntimeTab agent={agent} /> : null}
        {normalizedActiveTab === 'manifest' ? <ManifestViewer value={manifest} /> : null}
        {normalizedActiveTab === 'overview' ? <OverviewTab config={config} agent={agent} /> : null}
      </div>
    </form>
  );
}

function OverridesTab({
  config,
  agent,
  displayDraft,
  runtimeDraft,
  onDisplayChange,
  onRuntimeChange,
  profiles,
  saving,
  dirty,
  hasSavedOverrides,
  onReset,
  onWriteManifest,
}: {
  config: AgentConfig;
  agent?: Agent;
  displayDraft: AgentDisplayOverrides;
  runtimeDraft: AgentRuntimeOverrides;
  onDisplayChange: (value: AgentDisplayOverrides) => void;
  onRuntimeChange: (value: AgentRuntimeOverrides) => void;
  profiles: { id: string; alias: string; name: string; enabled: boolean }[];
  saving: boolean;
  dirty: boolean;
  hasSavedOverrides: boolean;
  onReset: () => void;
  onWriteManifest: () => void;
}) {
  const resolved = config.resolved;
  const sections = resolved?.sections || [];
  const hasLlmSection = sections.some((section) => section.id === 'llm_runtime') || agent?.capabilities?.includes('llm') || config.manifest_summary.capabilities?.includes('llm');
  const isPromptAgent = (agent?.type || config.manifest_summary.type) === 'prompt';
  const runtime = resolved?.runtime || {};
  return (
    <div className="settings-runtime-stack">
      <section className="settings-override-section">
        <div className="detail-section-heading">
          <h3>Basic information</h3>
          <span className="settings-badge muted">{overrideCount(displayDraft)} overrides</span>
        </div>
        <OverrideTextField
          label="Name"
          field="display.name"
          value={displayDraft.name || ''}
          placeholder={resolved?.display?.name || config.manifest_summary.name || config.agent_id}
          config={config}
          savedValue={config.display?.name}
          onChange={(name) => onDisplayChange({ ...displayDraft, name })}
        />
        <OverrideTextField
          label="Avatar"
          field="display.avatar"
          value={displayDraft.avatar || ''}
          placeholder={resolved?.display?.avatar || config.manifest_summary.avatar || 'Generated initials'}
          config={config}
          savedValue={config.display?.avatar}
          onChange={(avatar) => onDisplayChange({ ...displayDraft, avatar })}
          previewLabel={displayDraft.avatar || resolved?.display?.avatar || resolved?.display?.name || config.agent_id}
        />
        <OverrideTextField
          label="Description"
          field="display.description"
          value={displayDraft.description || ''}
          placeholder={resolved?.display?.description || config.manifest_summary.description || 'No description'}
          config={config}
          savedValue={config.display?.description}
          onChange={(description) => onDisplayChange({ ...displayDraft, description })}
          textarea
        />
      </section>

      {isPromptAgent ? (
        <section className="settings-override-section">
          <div className="detail-section-heading">
            <h3>Prompt</h3>
            <span className="settings-badge muted">{runtimeDraft.prompt ? 1 : 0} overrides</span>
          </div>
          <OverrideTextField
            label="System prompt"
            field="runtime.prompt"
            value={runtimeDraft.prompt || ''}
            placeholder={String(runtime.prompt || 'No manifest prompt')}
            config={config}
            savedValue={config.runtime?.prompt}
            onChange={(prompt) => onRuntimeChange({ ...runtimeDraft, prompt })}
            textarea
          />
        </section>
      ) : null}

      {hasLlmSection ? (
        <section className="settings-override-section">
          <div className="detail-section-heading">
            <h3>LLM Runtime Settings</h3>
            <span className="settings-badge muted">{overrideCount(omitKeys(runtimeDraft, ['prompt']))} overrides</span>
          </div>
          <OverrideSelect
            label="LLM profile"
            field="runtime.llm_profile_id"
            value={runtimeDraft.llm_profile_id || ''}
            config={config}
            onChange={(llm_profile_id) => onRuntimeChange({ ...runtimeDraft, llm_profile_id: llm_profile_id || undefined })}
          >
            <option value="">Use manifest/default</option>
            {profiles.map((profile) => (
              <option key={profile.id} value={profile.id} disabled={!profile.enabled}>
                {profile.name} ({profile.alias}){profile.enabled ? '' : ' - disabled'}
              </option>
            ))}
          </OverrideSelect>
          <OverrideSelect
            label="Allow session override"
            field="runtime.allow_session_override"
            value={runtimeDraft.allow_session_override === undefined ? '' : String(runtimeDraft.allow_session_override)}
            config={config}
            onChange={(value) => onRuntimeChange({ ...runtimeDraft, allow_session_override: value === '' ? undefined : value === 'true' })}
          >
            <option value="">Use manifest/default ({runtime.allow_session_override === false ? 'No' : 'Yes'})</option>
            <option value="true">Yes</option>
            <option value="false">No</option>
          </OverrideSelect>
          <OverrideSelect
            label="Context policy"
            field="runtime.context_policy"
            value={runtimeDraft.context_policy?.mode || ''}
            config={config}
            onChange={(mode) =>
              onRuntimeChange({
                ...runtimeDraft,
                context_policy: mode
                  ? { ...(runtime.context_policy as ContextPolicy), ...(runtimeDraft.context_policy || {}), mode: mode as ContextPolicy['mode'] }
                  : undefined,
              })
            }
          >
            <option value="">Use manifest/default ({runtime.context_policy?.mode || 'recent_messages'})</option>
            <option value="current_message">current_message</option>
            <option value="recent_messages">recent_messages</option>
            <option value="none">none</option>
          </OverrideSelect>
          <OverrideNumber
            label="Max history messages"
            field="runtime.context_policy"
            value={runtimeDraft.context_policy?.max_messages ?? ''}
            config={config}
            min={0}
            max={100}
            disabled={(runtimeDraft.context_policy?.mode || runtime.context_policy?.mode) === 'none'}
            onChange={(max_messages) =>
              onRuntimeChange({
                ...runtimeDraft,
                context_policy: {
                  ...(runtime.context_policy as ContextPolicy),
                  ...(runtimeDraft.context_policy || {}),
                  max_messages: max_messages === '' ? undefined : Number(max_messages),
                },
              })
            }
          />
          <OverrideSelect
            label="Model lifecycle unload"
            field="runtime.model_lifecycle"
            value={runtimeDraft.model_lifecycle?.unload || ''}
            config={config}
            onChange={(unload) =>
              onRuntimeChange({
                ...runtimeDraft,
                model_lifecycle: unload ? { load: 'on_demand', unload: unload as ModelLifecyclePolicy['unload'], unload_failure: runtimeDraft.model_lifecycle?.unload_failure || runtime.model_lifecycle?.unload_failure || 'warn' } : undefined,
              })
            }
          >
            <option value="">Use manifest/default ({runtime.model_lifecycle?.unload || 'never'})</option>
            <option value="never">never</option>
            <option value="after_run">after_run</option>
          </OverrideSelect>
          <OverrideSelect
            label="Unload failure behavior"
            field="runtime.model_lifecycle"
            value={runtimeDraft.model_lifecycle?.unload_failure || ''}
            config={config}
            onChange={(unload_failure) =>
              onRuntimeChange({
                ...runtimeDraft,
                model_lifecycle: unload_failure ? { load: 'on_demand', unload: runtimeDraft.model_lifecycle?.unload || runtime.model_lifecycle?.unload || 'never', unload_failure: unload_failure as ModelLifecyclePolicy['unload_failure'] } : undefined,
              })
            }
          >
            <option value="">Use manifest/default ({runtime.model_lifecycle?.unload_failure || 'warn'})</option>
            <option value="ignore">ignore</option>
            <option value="warn">warn</option>
            <option value="fail">fail</option>
          </OverrideSelect>
          <OverrideNumber
            label="Timeout seconds"
            field="runtime.timeout_seconds"
            value={runtimeDraft.timeout_seconds ?? ''}
            config={config}
            min={1}
            max={3600}
            onChange={(timeout_seconds) => onRuntimeChange({ ...runtimeDraft, timeout_seconds: timeout_seconds === '' ? undefined : Number(timeout_seconds) })}
          />
        </section>
      ) : null}

      <div className="settings-override-footer">
        <button className="settings-secondary-button" type="button" disabled={!hasSavedOverrides || saving} onClick={onReset}>
          <RotateCcw size={14} />
          Reset overrides
        </button>
        <button className="settings-secondary-button danger" type="button" disabled={(!hasSavedOverrides && !dirty) || saving} onClick={onWriteManifest}>
          <Upload size={14} />
          Write overrides to manifest
        </button>
      </div>
    </div>
  );
}

function OverrideTextField(props: {
  label: string;
  field: string;
  value: string;
  placeholder: string;
  config: AgentConfig;
  savedValue?: string;
  onChange: (value: string) => void;
  textarea?: boolean;
  previewLabel?: string;
}) {
  const badge = sourceBadge(props.config, props.field, props.value, props.savedValue);
  return (
    <label className={`settings-override-field ${badge === 'Override' ? 'overridden' : ''}`}>
      <span>
        {props.label}
        {badge === 'Unsaved *' ? ' *' : ''}
        <SourceBadge value={badge} />
      </span>
      <div className="settings-override-input-row">
        {props.previewLabel ? <div className="settings-avatar-preview">{props.previewLabel.slice(0, 3)}</div> : null}
        {props.textarea ? (
          <textarea value={props.value} placeholder={props.placeholder} onChange={(event) => props.onChange(event.target.value)} />
        ) : (
          <input value={props.value} placeholder={props.placeholder} onChange={(event) => props.onChange(event.target.value)} />
        )}
      </div>
    </label>
  );
}

function OverrideSelect({ label, field, value, config, onChange, children }: { label: string; field: string; value: string; config: AgentConfig; onChange: (value: string) => void; children: ReactNode }) {
  const badge = sourceBadge(config, field, value, value || undefined);
  return (
    <label className={`settings-override-field ${badge === 'Override' ? 'overridden' : ''}`}>
      <span>
        {label}
        {badge === 'Unsaved *' ? ' *' : ''}
        <SourceBadge value={badge} />
      </span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {children}
      </select>
    </label>
  );
}

function OverrideNumber(props: { label: string; field: string; value: number | ''; config: AgentConfig; min: number; max: number; disabled?: boolean; onChange: (value: number | '') => void }) {
  const badge = sourceBadge(props.config, props.field, props.value, props.value === '' ? undefined : String(props.value));
  return (
    <label className={`settings-override-field ${badge === 'Override' ? 'overridden' : ''}`}>
      <span>
        {props.label}
        {badge === 'Unsaved *' ? ' *' : ''}
        <SourceBadge value={badge} />
      </span>
      <input
        type="number"
        min={props.min}
        max={props.max}
        value={props.value}
        disabled={props.disabled}
        onChange={(event) => props.onChange(event.target.value === '' ? '' : Number(event.target.value))}
      />
    </label>
  );
}

function SourceBadge({ value }: { value: string }) {
  const className = value === 'Override' ? 'success' : value === 'Unsaved *' ? 'warning' : 'muted';
  return <span className={`settings-badge ${className}`}>{value}</span>;
}

function sourceBadge(config: AgentConfig, field: string, draftValue: unknown, savedValue: unknown): string {
  const empty = draftValue === '' || draftValue === undefined || draftValue === null;
  const savedEmpty = savedValue === '' || savedValue === undefined || savedValue === null;
  if (!empty || !savedEmpty) {
    if (JSON.stringify(draftValue || '') !== JSON.stringify(savedValue || '')) return 'Unsaved *';
  }
  const source = config.field_sources?.[field] || config.resolved?.field_sources?.[field] || 'default';
  if (source === 'override') return 'Override';
  if (source === 'manifest') return 'Manifest';
  return 'Default';
}

function overrideCount(value: Record<string, unknown>): number {
  return Object.entries(value).filter(([, item]) => item !== undefined && item !== null && item !== '').length;
}

function normalizedDisplayDraft(display: AgentDisplayOverrides, config: AgentConfig): AgentDisplayOverrides {
  const manifest = config.manifest || config.manifest_summary;
  return {
    ...(display.name?.trim() && display.name.trim() !== manifest.name ? { name: display.name.trim() } : {}),
    ...(display.description?.trim() && display.description.trim() !== manifest.description ? { description: display.description.trim() } : {}),
    ...(display.avatar?.trim() && display.avatar.trim() !== (manifest.avatar || '') ? { avatar: display.avatar.trim() } : {}),
  };
}

function normalizedRuntimeDraft(runtime: AgentRuntimeOverrides, config: AgentConfig): AgentRuntimeOverrides {
  const resolved = config.resolved?.runtime || {};
  const result: AgentRuntimeOverrides = {};
  if (runtime.llm_profile_id) result.llm_profile_id = runtime.llm_profile_id;
  const manifestPrompt = config.manifest?.prompt || '';
  if (runtime.prompt && runtime.prompt !== manifestPrompt) {
    result.prompt = runtime.prompt;
  }
  if (runtime.allow_session_override !== undefined && runtime.allow_session_override !== resolved.allow_session_override) result.allow_session_override = runtime.allow_session_override;
  if (runtime.context_policy) result.context_policy = runtime.context_policy;
  if (runtime.model_lifecycle) result.model_lifecycle = runtime.model_lifecycle;
  if (runtime.timeout_seconds !== undefined && runtime.timeout_seconds !== resolved.timeout_seconds) result.timeout_seconds = runtime.timeout_seconds;
  return result;
}

function omitKeys<T extends Record<string, unknown>>(value: T, keys: string[]): Record<string, unknown> {
  return Object.fromEntries(Object.entries(value).filter(([key]) => !keys.includes(key)));
}

function OverviewTab({ config, agent }: { config: AgentConfig; agent?: Agent }) {
  const summary = config.manifest_summary;
  return (
    <div className="settings-detail-grid">
      <InfoRow label="Description" value={config.resolved?.display?.description || summary.description || agent?.description || 'No description.'} wide />
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
