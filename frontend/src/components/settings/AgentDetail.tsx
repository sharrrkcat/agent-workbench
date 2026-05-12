import { RotateCcw, Save, Upload } from 'lucide-react';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { Agent, AgentAction, AgentConfig, AgentDisplayOverrides, AgentRuntimeOverrides, ContextPolicy, GeneralSettings, ModelLifecyclePolicy } from '../../types';
import { AgentAvatar } from '../AgentAvatar';
import { ConfigForm } from './ConfigForm';
import { DetailTabs } from './DetailTabs';
import { ManifestViewer } from './ManifestViewer';
import { ToggleSwitch } from './ToggleSwitch';
import { buildUserConfig, displayValue, initialConfigValues, isConfigDirty, type ConfigValues } from './configUtils';
import { getResolvedAgentDisplay, resolvedAgentProfileLabel } from '../../utils/agents';

const baseTabIds = ['overview', 'overrides', 'actions', 'config', 'runtime', 'intentRouting', 'manifest'] as const;

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
  const { t } = useTranslation(['agents', 'common']);
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
  const display = getResolvedAgentDisplay(config);
  const name = display.name || summary.name || agent?.name || config.agent_id;
  const hasActions = Boolean(agent?.actions?.length);
  const hasConfigFields = Boolean(config.config_schema?.length);
  const hasRuntime = Boolean(agent?.context_policy || agent?.model_lifecycle || agent?.llm || agent?.model || agent?.type === 'script');
  const manifest = useMemo(() => ({ agent, config }), [agent, config]);
  const tabs = useMemo(
    () =>
      baseTabIds.map((id) => ({
        id,
        label: t(`agents:tabs.${id}`),
        enabled:
          id === 'overview' ||
          id === 'overrides' ||
          (id === 'actions' && hasActions) ||
          (id === 'config' && hasConfigFields) ||
          (id === 'runtime' && hasRuntime) ||
          id === 'intentRouting' ||
          id === 'manifest',
      })),
    [hasActions, hasConfigFields, hasRuntime, t],
  );
  const normalizedActiveTab = tabs.some((tab) => tab.id === activeTab && tab.enabled !== false) ? activeTab : 'overview';
  const showOverridesSave = overridesDirty;
  const showConfigSave = dirty && !showOverridesSave;

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
      setLocalError(error instanceof Error ? error.message : t('agents:errors.saveConfig'));
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
      setLocalError(error instanceof Error ? error.message : t('agents:errors.saveOverrides'));
    }
  }

  async function resetOverrides() {
    if (!window.confirm(t('agents:confirm.resetOverrides'))) return;
    try {
      setLocalError('');
      await resetAgentOverrides(config.agent_id);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : t('agents:errors.resetOverrides'));
    }
  }

  async function writeManifest() {
    if (
      !window.confirm(
        t('agents:confirm.writeManifest', { agentId: config.agent_id }),
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
      setLocalError(error instanceof Error ? error.message : t('agents:errors.writeManifest'));
    }
  }

  return (
    <form className="settings-detail-form" onSubmit={save}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <AgentAvatar agent={display} label={name} className="settings-detail-avatar" iconSize={18} />
          <div>
            <h2>{name}</h2>
            <p>
              <code>{config.agent_id}</code>
              <span>{summary.type || agent?.type || 'agent'}</span>
            </p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {showOverridesSave ? (
            <button className="settings-primary-button" type="button" disabled={isSaving} onClick={saveOverrides}>
              <Save size={14} />
              {isSaving ? t('common:saving') : t('common:save')}
            </button>
          ) : null}
          {showConfigSave ? (
            <button className="settings-primary-button" type="submit" disabled={isSaving}>
              <Save size={14} />
              {isSaving ? t('common:saving') : t('common:save')}
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
            emptyMessage={t('agents:empty.noConfigurableFields')}
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
            t={t}
          />
        ) : null}
        {normalizedActiveTab === 'runtime' ? <RuntimeTab agent={agent} /> : null}
        {normalizedActiveTab === 'intentRouting' ? (
          <IntentRoutingTab
            config={config}
            agent={agent}
            runtimeDraft={runtimeDraft}
            onRuntimeChange={setRuntimeDraft}
            t={t}
          />
        ) : null}
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
  t,
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
  t: ReturnType<typeof useTranslation>['t'];
}) {
  const resolved = config.resolved;
  const sections = resolved?.sections || [];
  const isPromptAgent = (agent?.type || config.manifest_summary.type) === 'prompt';
  const hasLlmSection = sections.some((section) => section.id === 'llm_runtime') || agent?.capabilities?.includes('llm') || config.manifest_summary.capabilities?.includes('llm');
  const hasKnowledgeSection = sections.some((section) => section.id === 'knowledge_runtime') || isPromptAgent || hasLlmSection;
  const runtime = resolved?.runtime || {};
  return (
    <div className="settings-runtime-stack">
      <section className="settings-override-section">
        <div className="detail-section-heading">
          <h3>{t('agents:sections.basic')}</h3>
          <span className="settings-badge muted">{t('agents:summary.overrideCount', { count: overrideCount(displayDraft) })}</span>
        </div>
        <OverrideTextField
          label={t('agents:labels.name')}
          field="display.name"
          value={displayDraft.name || ''}
          placeholder={resolved?.display?.name || config.manifest_summary.name || config.agent_id}
          config={config}
          savedValue={config.display?.name}
          onChange={(name) => onDisplayChange({ ...displayDraft, name })}
        />
        <OverrideTextField
          label={t('agents:labels.avatar')}
          field="display.avatar"
          value={displayDraft.avatar || ''}
          placeholder={resolved?.display?.avatar || config.manifest_summary.avatar || t('agents:placeholders.generatedInitials')}
          config={config}
          savedValue={config.display?.avatar}
          onChange={(avatar) => onDisplayChange({ ...displayDraft, avatar })}
          previewAgent={avatarPreviewAgent(config, displayDraft)}
        />
        <OverrideTextField
          label={t('agents:labels.description')}
          field="display.description"
          value={displayDraft.description || ''}
          placeholder={resolved?.display?.description || config.manifest_summary.description || t('agents:placeholders.noDescription')}
          config={config}
          savedValue={config.display?.description}
          onChange={(description) => onDisplayChange({ ...displayDraft, description })}
          textarea
        />
      </section>

      {isPromptAgent ? (
        <section className="settings-override-section">
          <div className="detail-section-heading">
            <h3>{t('agents:sections.prompt')}</h3>
            <span className="settings-badge muted">{t('agents:summary.overrideCount', { count: runtimeDraft.prompt ? 1 : 0 })}</span>
          </div>
          <OverrideTextField
            label={t('agents:labels.systemPrompt')}
            field="runtime.prompt"
            value={runtimeDraft.prompt || ''}
            placeholder={String(runtime.prompt || t('agents:placeholders.noManifestPrompt'))}
            config={config}
            savedValue={config.runtime?.prompt}
            onChange={(prompt) => onRuntimeChange({ ...runtimeDraft, prompt })}
            textarea
          />
        </section>
      ) : null}

      {hasKnowledgeSection ? (
        <section className="settings-override-section">
          <div className="detail-section-heading">
            <h3>{t('agents:sections.knowledgeRuntime', { defaultValue: 'Knowledge Runtime Settings' })}</h3>
            <span className="settings-badge muted">{t('agents:summary.overrideCount', { count: runtimeDraft.knowledge_context_mode ? 1 : 0 })}</span>
          </div>
          <p className="settings-muted-text">
            {t('agents:help.knowledgeRuntime', { defaultValue: 'Prompt Agents use Session KBs by default. LLM Script Agents do not use them unless enabled here.' })}
          </p>
          <OverrideSelect
            label={t('agents:labels.useSessionKnowledgeBases', { defaultValue: 'Use session knowledge bases' })}
            field="runtime.knowledge_context_mode"
            value={runtimeDraft.knowledge_context_mode || ''}
            config={config}
            onChange={(knowledge_context_mode) =>
              onRuntimeChange({
                ...runtimeDraft,
                knowledge_context_mode: knowledge_context_mode ? knowledge_context_mode as AgentRuntimeOverrides['knowledge_context_mode'] : undefined,
              })
            }
          >
            <option value="">Use default ({runtime.knowledge_context_effective_mode || runtime.knowledge_context_default_effective_mode || (isPromptAgent ? 'enabled' : 'disabled')})</option>
            <option value="enabled">{t('common:enabled')}</option>
            <option value="disabled">{t('common:disabled')}</option>
          </OverrideSelect>
        </section>
      ) : null}

      {hasLlmSection ? (
        <section className="settings-override-section">
          <div className="detail-section-heading">
            <h3>{t('agents:sections.llmRuntime')}</h3>
            <span className="settings-badge muted">{t('agents:summary.overrideCount', { count: overrideCount(pickKeys(runtimeDraft, ['llm_profile_id', 'allow_session_override', 'context_policy', 'model_lifecycle', 'timeout_seconds'])) })}</span>
          </div>
          <OverrideSelect
            label={t('agents:labels.modelProfile')}
            field="runtime.llm_profile_id"
            value={runtimeDraft.llm_profile_id || ''}
            config={config}
            onChange={(llm_profile_id) => onRuntimeChange({ ...runtimeDraft, llm_profile_id: llm_profile_id || undefined })}
          >
            <option value="">Use manifest/default</option>
            {profiles.map((profile) => (
              <option key={profile.id} value={profile.id} disabled={!profile.enabled}>
                {profile.name} ({profile.alias}){profile.enabled ? '' : ` - ${t('common:disabled')}`}
              </option>
            ))}
          </OverrideSelect>
          <OverrideSelect
            label={t('agents:labels.allowSessionOverride')}
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
            label={t('agents:labels.contextPolicy')}
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
            label={t('agents:labels.maxHistoryMessages')}
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
            label={t('agents:labels.modelLifecycleUnload')}
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
            label={t('agents:labels.unloadFailureBehavior')}
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
            label={t('agents:labels.timeoutSeconds')}
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
          {t('agents:buttons.resetOverrides')}
        </button>
        <button className="settings-secondary-button danger" type="button" disabled={(!hasSavedOverrides && !dirty) || saving} onClick={onWriteManifest}>
          <Upload size={14} />
          {t('agents:buttons.writeOverridesToManifest')}
        </button>
      </div>
    </div>
  );
}

function IntentRoutingTab({
  config,
  agent,
  runtimeDraft,
  onRuntimeChange,
  t,
}: {
  config: AgentConfig;
  agent?: Agent;
  runtimeDraft: AgentRuntimeOverrides;
  onRuntimeChange: (value: AgentRuntimeOverrides) => void;
  t: ReturnType<typeof useTranslation>['t'];
}) {
  const generalSettings = useWorkbenchStore((state) => state.generalSettings);
  const runtime = config.resolved?.runtime || {};
  const agentType = agent?.type || config.manifest_summary.type;
  const isPromptAgent = agentType === 'prompt';
  const isScriptAgent = agentType === 'script';
  const effectiveMode = runtimeDraft.intent_routing_mode || runtime.intent_routing_mode;

  return (
    <div className="settings-runtime-stack">
      {isPromptAgent ? (
        <section className="settings-override-section">
          <div className="detail-section-heading">
            <h3>{t('agents:sections.intentRoutingEntry')}</h3>
            <span className="settings-badge muted">{t('agents:summary.overrideCount', { count: runtimeDraft.intent_routing_mode ? 1 : 0 })}</span>
          </div>
          <p className="settings-muted-text">{t('agents:help.promptIntentRoutingEntry')}</p>
          <p className="settings-muted-text">{t('agents:help.intentRoutingExplicitBypass')}</p>
          <OverrideSelect
            label={t('agents:labels.intentRouting')}
            field="runtime.intent_routing_mode"
            value={runtimeDraft.intent_routing_mode || ''}
            config={config}
            onChange={(intent_routing_mode) =>
              onRuntimeChange({
                ...runtimeDraft,
                intent_routing_mode: intent_routing_mode ? intent_routing_mode as AgentRuntimeOverrides['intent_routing_mode'] : undefined,
              })
            }
          >
            <option value="">{t('agents:intentRouting.useDefault')}</option>
            <option value="enabled">{t('common:enabled')}</option>
            <option value="disabled">{t('common:disabled')}</option>
          </OverrideSelect>
          <p className="settings-muted-text">{intentRoutingEffectiveLabel(effectiveMode, generalSettings, t)}</p>
        </section>
      ) : null}

      {!isPromptAgent ? (
        <p className="settings-muted-text">
          {isScriptAgent ? t('agents:help.scriptIntentRoutingEntryUnsupported') : t('agents:help.nonPromptIntentRoutingEntryUnsupported')}
        </p>
      ) : null}

      <section className="settings-override-section">
        <div className="detail-section-heading">
          <h3>{t('agents:sections.intentRoutingTargetHints')}</h3>
          <span className="settings-badge muted">{t('agents:summary.overrideCount', { count: overrideCount({ aliases: runtimeDraft.intent_routing_aliases_text, examples: runtimeDraft.intent_routing_examples_text }) })}</span>
        </div>
        <p className="settings-muted-text">{t('agents:help.intentRoutingTargetHints')}</p>
        {isScriptAgent ? <p className="settings-muted-text">{t('agents:help.scriptIntentRoutingTargetHints')}</p> : null}
        <OverrideTextField
          label={t('agents:labels.routingAliases')}
          field="runtime.intent_routing_aliases_text"
          value={runtimeDraft.intent_routing_aliases_text || ''}
          placeholder={t('agents:placeholders.routingAliases')}
          config={config}
          savedValue={config.runtime?.intent_routing_aliases_text}
          onChange={(intent_routing_aliases_text) => onRuntimeChange({ ...runtimeDraft, intent_routing_aliases_text })}
        />
        <p className="settings-muted-text">{t('agents:help.routingAliases')}</p>
        <OverrideTextField
          label={t('agents:labels.routingExamples')}
          field="runtime.intent_routing_examples_text"
          value={runtimeDraft.intent_routing_examples_text || ''}
          placeholder={t('agents:placeholders.routingExamples')}
          config={config}
          savedValue={config.runtime?.intent_routing_examples_text}
          onChange={(intent_routing_examples_text) => onRuntimeChange({ ...runtimeDraft, intent_routing_examples_text })}
          textarea
        />
        <p className="settings-muted-text">{t('agents:help.routingExamples')}</p>
        <p className="settings-muted-text">{t('agents:help.genericRoutesNotAutoExecuted')}</p>
      </section>
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
  previewAgent?: ReturnType<typeof getResolvedAgentDisplay>;
}) {
  const badge = sourceBadge(props.config, props.field, props.value, props.savedValue);
  return (
    <label className={`settings-override-field ${badge === 'override' ? 'overridden' : ''}`}>
      <span>
        {props.label}
        {badge === 'unsaved' ? ' *' : ''}
        <SourceBadge value={badge} />
      </span>
      <div className="settings-override-input-row">
        {props.previewAgent ? <AgentAvatar agent={props.previewAgent} label={props.previewAgent.name} className="settings-avatar-preview" iconSize={14} /> : null}
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
    <label className={`settings-override-field ${badge === 'override' ? 'overridden' : ''}`}>
      <span>
        {label}
        {badge === 'unsaved' ? ' *' : ''}
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
    <label className={`settings-override-field ${badge === 'override' ? 'overridden' : ''}`}>
      <span>
        {props.label}
        {badge === 'unsaved' ? ' *' : ''}
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
  const { t } = useTranslation(['agents']);
  const className = value === 'override' ? 'success' : value === 'unsaved' ? 'warning' : 'muted';
  return <span className={`settings-badge ${className}`}>{t(`agents:source.${value}`, { defaultValue: value })}</span>;
}

function sourceBadge(config: AgentConfig, field: string, draftValue: unknown, savedValue: unknown): string {
  const empty = draftValue === '' || draftValue === undefined || draftValue === null;
  const savedEmpty = savedValue === '' || savedValue === undefined || savedValue === null;
  if (!empty || !savedEmpty) {
    if (JSON.stringify(draftValue || '') !== JSON.stringify(savedValue || '')) return 'unsaved';
  }
  const source = config.field_sources?.[field] || config.resolved?.field_sources?.[field] || 'default';
  if (source === 'override') return 'override';
  if (source === 'manifest') return 'manifest';
  return 'default';
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

function avatarPreviewAgent(config: AgentConfig, displayDraft: AgentDisplayOverrides): ReturnType<typeof getResolvedAgentDisplay> {
  const resolved = getResolvedAgentDisplay(config);
  if (!displayDraft.avatar?.trim()) return resolved;
  const avatar = displayDraft.avatar.trim();
  const isImage = /^https?:\/\//i.test(avatar) || avatar.startsWith('/');
  return {
    ...resolved,
    avatar: isImage ? null : avatar,
    avatar_type: isImage ? 'image' : 'text',
    avatar_url: isImage ? avatar : null,
  };
}

function normalizedRuntimeDraft(runtime: AgentRuntimeOverrides, config: AgentConfig): AgentRuntimeOverrides {
  const result: AgentRuntimeOverrides = {};
  if (runtime.llm_profile_id) result.llm_profile_id = runtime.llm_profile_id;
  const manifestPrompt = config.manifest?.prompt || '';
  if (runtime.prompt && runtime.prompt !== manifestPrompt) {
    result.prompt = runtime.prompt;
  }
  if (runtime.allow_session_override !== undefined) result.allow_session_override = runtime.allow_session_override;
  if (runtime.knowledge_context_mode) result.knowledge_context_mode = runtime.knowledge_context_mode;
  if (runtime.intent_routing_mode) result.intent_routing_mode = runtime.intent_routing_mode;
  if (runtime.intent_routing_aliases_text?.trim()) result.intent_routing_aliases_text = runtime.intent_routing_aliases_text.trim();
  if (runtime.intent_routing_examples_text?.trim()) result.intent_routing_examples_text = runtime.intent_routing_examples_text.trim();
  if (runtime.context_policy) result.context_policy = runtime.context_policy;
  if (runtime.model_lifecycle) result.model_lifecycle = runtime.model_lifecycle;
  if (runtime.timeout_seconds !== undefined) result.timeout_seconds = runtime.timeout_seconds;
  return result;
}

function intentRoutingEffectiveLabel(mode: AgentRuntimeOverrides['intent_routing_mode'] | undefined, settings: GeneralSettings | undefined, t: ReturnType<typeof useTranslation>['t']): string {
  if (!settings?.intent_routing_enabled) return t('agents:intentRouting.effectiveGeneralOff');
  const routeMode = settings.intent_routing_mode === 'auto' ? t('agents:intentRouting.autoMode') : t('agents:intentRouting.shadowMode');
  if (mode === 'enabled') return t('agents:intentRouting.effectiveAgentEnabled', { mode: routeMode });
  if (mode === 'disabled') return t('agents:intentRouting.effectiveAgentDisabled');
  if (settings.intent_routing_default_for_prompt_agents) return t('agents:intentRouting.effectiveDefaultEnabled', { mode: routeMode });
  return t('agents:intentRouting.effectiveDefaultDisabled');
}

function pickKeys<T extends Record<string, unknown>>(value: T, keys: string[]): Record<string, unknown> {
  return Object.fromEntries(Object.entries(value).filter(([key]) => keys.includes(key)));
}

function OverviewTab({ config, agent }: { config: AgentConfig; agent?: Agent }) {
  const { t } = useTranslation(['agents']);
  const summary = config.manifest_summary;
  return (
    <div className="settings-detail-grid">
      <InfoRow label={t('agents:labels.description')} value={config.resolved?.display?.description || summary.description || agent?.description || t('agents:placeholders.noDescription')} wide />
      <InfoRow label={t('agents:labels.type')} value={summary.type || agent?.type || 'agent'} />
      <div className="settings-info-row">
        <span>{t('agents:labels.capabilities')}</span>
        <div className="settings-chip-row">
          {agent?.capabilities?.length ? (
            agent.capabilities.map((capability) => <span key={capability}>{capability}</span>)
          ) : (
            <small>{t('agents:empty.noDeclaredCapabilities')}</small>
          )}
        </div>
      </div>
      <InfoRow label={t('agents:labels.contextPolicy')} value={summarizeContextPolicy(agent?.context_policy, t)} />
      <InfoRow label={t('agents:labels.modelLifecycle')} value={summarizeLifecycle(agent?.model_lifecycle, t)} />
      <InfoRow label={t('agents:labels.llm')} value={summarizeLlm(agent, t)} />
    </div>
  );
}

function ActionsTab({ actions }: { actions: AgentAction[] }) {
  const { t } = useTranslation(['agents', 'common', 'status']);
  if (!actions.length) {
    return <div className="settings-empty-state">{t('agents:empty.noActions')}</div>;
  }
  return (
    <div className="settings-table-wrap">
      <table className="settings-table">
        <thead>
          <tr>
            <th>{t('agents:labels.action')}</th>
            <th>{t('agents:labels.label')}</th>
            <th>{t('agents:labels.description')}</th>
            <th>{t('agents:labels.instruction')}</th>
            <th>{t('agents:labels.callable')}</th>
            <th>{t('agents:labels.context')}</th>
          </tr>
        </thead>
        <tbody>
          {actions.map((action) => (
            <tr key={action.id}>
              <td>
                <code>{action.id}</code>
              </td>
              <td>{action.label || (action.id === 'default' ? t('common:default') : t('status:common.unset'))}</td>
              <td>{action.description || t('status:common.none')}</td>
              <td>{action.instruction || t('status:common.none')}</td>
              <td>{action.callable ? t('status:common.yes') : t('status:common.no')}</td>
              <td>{summarizeContextPolicy(action.context_policy, t)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RuntimeTab({ agent }: { agent?: Agent }) {
  const { t } = useTranslation(['agents', 'status']);
  return (
    <div className="settings-runtime-stack">
      <section className="detail-section">
        <h3>{t('agents:sections.contextPolicy')}</h3>
        <PolicyGrid policy={agent?.context_policy} />
      </section>
      <section className="detail-section">
        <h3>{t('agents:sections.modelLifecycle')}</h3>
        <dl className="settings-definition-grid">
          <div>
            <dt>{t('agents:labels.load')}</dt>
            <dd>{agent?.model_lifecycle?.load || t('status:common.unset')}</dd>
          </div>
          <div>
            <dt>{t('agents:labels.unload')}</dt>
            <dd>{agent?.model_lifecycle?.unload || t('status:common.unset')}</dd>
          </div>
          <div>
            <dt>{t('agents:labels.unloadFailure')}</dt>
            <dd>{agent?.model_lifecycle?.unload_failure || t('status:common.unset')}</dd>
          </div>
        </dl>
      </section>
      <section className="detail-section">
        <h3>{t('agents:sections.llmRouting')}</h3>
        <LlmRuntimeSummary agent={agent} />
      </section>
      <section className="detail-section">
        <h3>{t('agents:sections.legacyModel')}</h3>
        {agent?.model ? <ManifestViewer value={agent.model} /> : <div className="settings-empty-state">{t('agents:empty.usesGlobalLlmFallback')}</div>}
      </section>
      {agent?.type === 'script' ? (
        <p className="settings-warning-text">{t('agents:help.scriptTrusted')}</p>
      ) : null}
    </div>
  );
}

function PolicyGrid({ policy }: { policy?: ContextPolicy | null }) {
  const { t } = useTranslation(['agents', 'status']);
  return (
    <dl className="settings-definition-grid">
      <div>
        <dt>{t('agents:labels.mode')}</dt>
        <dd>{policy?.mode || t('status:common.unset')}</dd>
      </div>
      <div>
        <dt>{t('agents:labels.maxMessages')}</dt>
        <dd>{displayValue(policy?.max_messages)}</dd>
      </div>
      <div>
        <dt>{t('agents:labels.maxChars')}</dt>
        <dd>{displayValue(policy?.max_chars)}</dd>
      </div>
      <div>
        <dt>{t('agents:labels.originalUserMessage')}</dt>
        <dd>{displayValue(policy?.include_original_user_message)}</dd>
      </div>
      <div>
        <dt>{t('agents:labels.lastAgentMessage')}</dt>
        <dd>{displayValue(policy?.include_last_agent_message)}</dd>
      </div>
    </dl>
  );
}

function LlmRuntimeSummary({ agent }: { agent?: Agent }) {
  const { t } = useTranslation(['agents', 'common', 'status']);
  const profiles = useWorkbenchStore((state) => state.llmProfiles);
  const resolvedLabel = resolvedAgentProfileLabel(agent, profiles);
  if (agent?.resolved_runtime?.llm_profile_id || agent?.resolved_runtime?.llm_profile_status === 'missing' || agent?.resolved_runtime?.llm_profile_status === 'disabled') {
    return (
      <dl className="settings-definition-grid">
        <div>
          <dt>{t('agents:labels.modelProfile')}</dt>
          <dd>{resolvedLabel || agent.resolved_runtime.llm_profile_id || t('common:default')}</dd>
        </div>
        <div>
          <dt>{t('agents:labels.sessionOverride')}</dt>
          <dd>{agent.resolved_runtime.allow_session_override === false ? t('status:common.no') : t('status:common.yes')}</dd>
        </div>
        <div>
          <dt>{t('agents:labels.source')}</dt>
          <dd>{agent.resolved_runtime.llm_profile_source || 'default'}</dd>
        </div>
      </dl>
    );
  }
  if (agent?.llm?.profile) {
    const overrides = ['temperature', 'top_p', 'top_k', 'max_tokens']
      .map((key) => [key, agent.llm?.[key as keyof NonNullable<Agent['llm']>]])
      .filter(([, value]) => value !== undefined && value !== null && value !== '');
    return (
      <dl className="settings-definition-grid">
        <div>
          <dt>{t('agents:labels.modelProfile')}</dt>
          <dd>{agent.llm.profile}</dd>
        </div>
        <div>
          <dt>{t('agents:labels.sessionOverride')}</dt>
          <dd>{agent.llm.allow_session_override === false ? t('status:common.no') : t('status:common.yes')}</dd>
        </div>
        <div>
          <dt>{t('agents:labels.overrides')}</dt>
          <dd>{overrides.length ? overrides.map(([key, value]) => `${key}: ${value}`).join(', ') : t('status:common.none')}</dd>
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
          <dt>{t('agents:sections.legacyModel')}</dt>
          <dd>{model}</dd>
        </div>
        <div>
          <dt>{t('agents:labels.provider')}</dt>
          <dd>{provider}</dd>
        </div>
        <div>
          <dt>{t('agents:labels.baseUrl')}</dt>
          <dd>{baseUrl}</dd>
        </div>
      </dl>
    );
  }
  return <div className="settings-empty-state">{t('agents:empty.usesGlobalLlmFallback')}</div>;
}

function InfoRow({ label, value, wide = false }: { label: string; value: unknown; wide?: boolean }) {
  return (
    <div className={`settings-info-row ${wide ? 'wide' : ''}`}>
      <span>{label}</span>
      <strong>{displayValue(value)}</strong>
    </div>
  );
}

function summarizeContextPolicy(policy: ContextPolicy | null | undefined, t: ReturnType<typeof useTranslation>['t']): string {
  if (!policy) return t('agents:summary.inheritedDefault');
  const parts: string[] = [policy.mode];
  if (policy.max_messages) parts.push(t('agents:summary.messages', { count: policy.max_messages }));
  if (policy.max_chars) parts.push(t('agents:summary.chars', { count: policy.max_chars }));
  return parts.join(' / ');
}

function summarizeLlm(agent: Agent | undefined, t: ReturnType<typeof useTranslation>['t']): string {
  if (agent?.llm?.profile) return t('agents:summary.llmProfile', { profile: agent.llm.profile });
  if (agent?.model) return t('agents:summary.legacyModel', { model: String(agent.model.model || agent.model.model_id || 'unset') });
  return t('agents:summary.usesGlobalLlmFallback');
}

function summarizeLifecycle(policy: ModelLifecyclePolicy | undefined, t: ReturnType<typeof useTranslation>['t']): string {
  if (!policy) return t('status:common.unset');
  return `${policy.load} / unload ${policy.unload} / failure ${policy.unload_failure}`;
}

