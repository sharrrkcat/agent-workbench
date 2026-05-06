import { FormEvent, KeyboardEvent, MouseEvent, useEffect, useState } from 'react';
import { Boxes, ChevronDown, ChevronRight, Settings } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { AgentConfig, CapabilityConfig, ConfigFieldSchema, LlmResolvedConfig, LlmTestResult } from '../types';
import { AgentAvatar } from './AgentAvatar';

type ConfigKind = 'agent' | 'capability';
type FormValues = Record<string, unknown>;

export function SettingsPanel({ showTitle = true }: { showTitle?: boolean }) {
  const { agentConfigs, capabilityConfigs } = useWorkbenchStore();

  return (
    <section className="settings-panel">
      {showTitle ? (
        <div className="panel-title">
          <Settings size={15} />
          Settings
        </div>
      ) : null}
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
  const { updateAgentConfig, updateCapabilityConfig, getResolvedLlmConfig, testLlmConnection, savingConfigId, testingLlm } =
    useWorkbenchStore();
  const [enabled, setEnabled] = useState(config.enabled);
  const [values, setValues] = useState<FormValues>(() => initialValues(config));
  const [formError, setFormError] = useState('');
  const [testResult, setTestResult] = useState<LlmTestResult | null>(null);
  const [resolvedLlm, setResolvedLlm] = useState<LlmResolvedConfig | null>(null);
  const [expanded, setExpanded] = useState(false);
  const fields = config.config_schema || [];
  const canExpand = fields.length > 0;
  const isLlm = kind === 'capability' && id === 'llm';
  const isSaving = savingConfigId === `${kind}:${id}`;
  const dirty = isDirty(config, enabled, fields, values);

  useEffect(() => {
    setEnabled(config.enabled);
    setValues(initialValues(config));
    setFormError('');
  }, [config]);

  useEffect(() => {
    if (!isLlm) return;
    void getResolvedLlmConfig().then(setResolvedLlm);
  }, [getResolvedLlmConfig, isLlm, config.updated_at]);

  async function save(event: FormEvent) {
    event.preventDefault();
    let userConfig: Record<string, unknown>;
    try {
      userConfig = buildUserConfig(fields, values);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Config is invalid.');
      return;
    }
    setFormError('');
    if (kind === 'agent') {
      await updateAgentConfig(id, { enabled, user_config: userConfig });
    } else {
      await updateCapabilityConfig(id, { enabled, user_config: userConfig });
      if (isLlm) {
        setResolvedLlm(await getResolvedLlmConfig());
      }
    }
  }

  async function runTest() {
    setTestResult(await testLlmConnection());
  }

  function toggleExpanded() {
    if (!canExpand) return;
    setExpanded((current) => !current);
  }

  function onHeaderKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!canExpand) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      toggleExpanded();
    }
  }

  function stopHeaderToggle(event: MouseEvent<HTMLElement>) {
    event.stopPropagation();
  }

  const label = name || id;

  return (
    <form className={`config-row ${enabled ? '' : 'disabled'} ${expanded ? 'expanded' : 'collapsed'}`} onSubmit={save}>
      <div
        className={`config-card-header ${canExpand ? 'expandable' : ''}`}
        role={canExpand ? 'button' : undefined}
        tabIndex={canExpand ? 0 : undefined}
        aria-expanded={canExpand ? expanded : undefined}
        onClick={toggleExpanded}
        onKeyDown={onHeaderKeyDown}
      >
        <div className="config-card-summary">
          {kind === 'agent' ? (
            <AgentAvatar agent={config.manifest_summary} label={label} className="config-card-avatar" iconSize={16} />
          ) : (
            <div className="config-card-avatar" aria-hidden="true">
              {initials(label) || <Boxes size={16} />}
            </div>
          )}
          <div className="config-card-title">
            <span>{label}</span>
            <small>{id}</small>
            {config.manifest_summary.description ? <p>{config.manifest_summary.description}</p> : null}
          </div>
        </div>
        <div className="config-card-controls" onClick={stopHeaderToggle} onKeyDown={(event) => event.stopPropagation()}>
          {dirty ? (
            <button type="submit" disabled={isSaving || testingLlm} onClick={stopHeaderToggle}>
              {isSaving ? 'Saving...' : 'Save'}
            </button>
          ) : null}
          <label className="toggle-switch" onClick={stopHeaderToggle}>
            <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
            <span aria-hidden="true" />
            <small>{enabled ? 'Enabled' : 'Disabled'}</small>
          </label>
          {canExpand ? (
            <button
              className="config-card-chevron"
              type="button"
              aria-label={expanded ? `Collapse ${label}` : `Expand ${label}`}
              aria-expanded={expanded}
              onClick={(event) => {
                stopHeaderToggle(event);
                toggleExpanded();
              }}
            >
              {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            </button>
          ) : null}
        </div>
      </div>

      {expanded && canExpand ? (
      <div className="config-card-body">
        {isLlm && resolvedLlm ? <LlmStatus status={resolvedLlm} /> : null}

        <div className="config-fields">
          {fields.map((field) => (
            <ConfigFieldEditor
              key={field.name}
              field={field}
              value={values[field.name]}
              onChange={(value) => setValues((current) => ({ ...current, [field.name]: value }))}
            />
          ))}
        </div>

        {formError ? <p>{formError}</p> : null}
        <div className="config-actions">
          {isLlm ? (
            <button type="button" disabled={isSaving || testingLlm} onClick={() => void runTest()}>
              {testingLlm ? 'Testing...' : 'Test connection'}
            </button>
          ) : null}
        </div>
        {isLlm && testResult?.models?.length ? (
          <label className="config-field">
            <span>Available models</span>
            <select value={String(values.model ?? '')} onChange={(event) => setValues((current) => ({ ...current, model: event.target.value }))}>
              <option value="">Select model</option>
              {testResult.models.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
            <small>Choose a model, then Save to store it in the LLM capability config.</small>
          </label>
        ) : null}
        {testResult ? (
          <p className={testResult.success ? 'config-success' : ''}>
            {testResult.message}
            {testResult.models?.length ? ` Models: ${testResult.models.join(', ')}` : ''}
          </p>
        ) : null}
      </div>
      ) : null}
    </form>
  );
}

function LlmStatus({ status }: { status: LlmResolvedConfig }) {
  return (
    <div className="llm-status">
      <span>Resolved LLM config</span>
      <dl>
        <div>
          <dt>Base URL</dt>
          <dd>{status.base_url || 'unset'}</dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd>{status.model || 'unset'}</dd>
        </div>
        <div>
          <dt>Timeout</dt>
          <dd>{status.timeout ?? 'unset'}</dd>
        </div>
        <div>
          <dt>API key</dt>
          <dd>{status.api_key_set ? 'yes' : 'no'}</dd>
        </div>
      </dl>
    </div>
  );
}

function ConfigFieldEditor({
  field,
  value,
  onChange,
}: {
  field: ConfigFieldSchema;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const label = field.label || field.name;
  const id = `config-${field.name}`;
  return (
    <label className="config-field" htmlFor={id}>
      <span>
        {label}
        {field.required ? <em>required</em> : null}
      </span>
      {renderInput(field, id, value, onChange)}
      {field.description ? <small>{field.description}</small> : null}
    </label>
  );
}

function renderInput(field: ConfigFieldSchema, id: string, value: unknown, onChange: (value: unknown) => void) {
  if (field.type === 'text') {
    return <textarea id={id} rows={3} value={String(value ?? '')} onChange={(event) => onChange(event.target.value)} />;
  }
  if (field.type === 'integer' || field.type === 'float') {
    return <input id={id} type="number" value={String(value ?? '')} onChange={(event) => onChange(event.target.value)} />;
  }
  if (field.type === 'boolean') {
    return <input id={id} type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} />;
  }
  if (field.type === 'enum') {
    return (
      <select id={id} value={String(value ?? '')} onChange={(event) => onChange(event.target.value)}>
        <option value="">Unset</option>
        {field.options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    );
  }
  if (field.type === 'json') {
    return (
      <textarea
        id={id}
        rows={4}
        value={typeof value === 'string' ? value : JSON.stringify(value ?? {}, null, 2)}
        onChange={(event) => onChange(event.target.value)}
        spellCheck={false}
      />
    );
  }
  return (
    <input
      id={id}
      type={field.secret ? 'password' : 'text'}
      value={String(value ?? '')}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

function initialValues(config: AgentConfig | CapabilityConfig): FormValues {
  const source = config.user_config || {};
  return Object.fromEntries((config.config_schema || []).map((field) => [field.name, source[field.name] ?? '']));
}

function buildUserConfig(fields: ConfigFieldSchema[], values: FormValues): Record<string, unknown> {
  const userConfig: Record<string, unknown> = {};
  for (const field of fields) {
    const value = values[field.name];
    if (value === '' || value === undefined) {
      continue;
    }
    if (field.type === 'integer') {
      const parsed = Number(value);
      if (!Number.isInteger(parsed)) throw new Error(`${field.label || field.name} must be an integer.`);
      userConfig[field.name] = parsed;
    } else if (field.type === 'float') {
      const parsed = Number(value);
      if (Number.isNaN(parsed)) throw new Error(`${field.label || field.name} must be a number.`);
      userConfig[field.name] = parsed;
    } else if (field.type === 'json') {
      if (typeof value === 'string') {
        userConfig[field.name] = JSON.parse(value);
      } else {
        userConfig[field.name] = value;
      }
    } else {
      userConfig[field.name] = value;
    }
  }
  return userConfig;
}

function isDirty(
  config: AgentConfig | CapabilityConfig,
  enabled: boolean,
  fields: ConfigFieldSchema[],
  values: FormValues,
): boolean {
  if (enabled !== config.enabled) return true;
  try {
    return stableConfigString(buildUserConfig(fields, values)) !== stableConfigString(config.user_config || {});
  } catch {
    return true;
  }
}

function stableConfigString(value: Record<string, unknown>): string {
  return JSON.stringify(sortObject(value));
}

function sortObject(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(sortObject);
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, sortObject(item)]),
    );
  }
  return value;
}

function initials(value: string): string {
  const words = value
    .replace(/[/_-]/g, ' ')
    .split(/\s+/)
    .filter(Boolean);
  return words
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase())
    .join('');
}
