import { Boxes, Save, Search } from 'lucide-react';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../api/client';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { CapabilityConfig, Command, WebSearchTestResult } from '../../types';
import { ConfigForm } from './ConfigForm';
import { DetailTabs } from './DetailTabs';
import { LlmSettingsPanel } from './LlmSettingsPanel';
import { ManifestViewer } from './ManifestViewer';
import { SettingsApiError, toSettingsError, type SettingsErrorValue } from './SettingsApiError';
import { ToggleSwitch } from './ToggleSwitch';
import { buildUserConfig, displayValue, initialConfigValues, initials, isConfigDirty, stableConfigString, type ConfigValues } from './configUtils';

const baseTabIds = ['overview', 'commands', 'config', 'health', 'manifest'] as const;

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
  const { t } = useTranslation(['capabilities', 'common']);
  const { updateCapabilityConfig, savingConfigId, testingLlm } = useWorkbenchStore();
  const scopeId = config.capability_id;
  const configBaselineKey = stableConfigString(buildUserConfig(config.config_schema || [], initialConfigValues(config)));
  const [enabled, setEnabled] = useState(config.enabled);
  const [values, setValues] = useState<ConfigValues>(() => initialConfigValues(config));
  const [draftReady, setDraftReady] = useState(() => ({ scopeId, configBaselineKey }));
  const [localError, setLocalError] = useState<SettingsErrorValue | null>(null);
  const [healthBusy, setHealthBusy] = useState(false);
  const isSaving = savingConfigId === `capability:${config.capability_id}`;
  const saveDisabled = isSaving || (config.capability_id === 'llm' && (testingLlm || healthBusy));
  const hydrated = draftReady.scopeId === scopeId && draftReady.configBaselineKey === configBaselineKey;
  const dirty = hydrated && isConfigDirty(config, enabled, values);
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
      baseTabIds.map((id) => ({
        id,
        label: t(`capabilities:tabs.${id}`),
        enabled:
          id === 'overview' ||
          (id === 'commands' && hasCommands) ||
          (id === 'config' && hasConfigFields) ||
          (id === 'health' && hasHealth) ||
          id === 'manifest',
      })),
    [hasCommands, hasConfigFields, hasHealth, t],
  );
  const normalizedActiveTab = tabs.some((tab) => tab.id === activeTab && tab.enabled !== false) ? activeTab : 'overview';

  useEffect(() => {
    setEnabled(config.enabled);
    setValues(initialConfigValues(config));
    setDraftReady({ scopeId, configBaselineKey });
    setLocalError(null);
    setHealthBusy(false);
  }, [config, configBaselineKey, scopeId]);

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
      setLocalError(toSettingsError(error, t('capabilities:errors.saveConfig')));
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
              <span>{t('capabilities:labels.capability')}</span>
            </p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {dirty ? (
            <button className="settings-primary-button" type="submit" disabled={saveDisabled}>
              <Save size={14} />
              {isSaving ? t('common:saving') : t('common:save')}
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
            <div className="settings-empty-state">{t('capabilities:empty.noHealthChecks')}</div>
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
  const { t } = useTranslation(['capabilities']);
  const fields = config.config_schema || [];
  if (config.capability_id === 'file') {
    return (
      <div className="settings-config-sections">
        <p className="settings-helper-text">
          {t('capabilities:help.fileSettings')}
        </p>
        <ConfigSection title={t('capabilities:sections.permissions')} fieldNames={['allowed_directories']} fields={fields} values={values} onChange={onChange} />
        <ConfigSection
          title={t('capabilities:sections.readLimits')}
          fieldNames={['max_local_text_read_size_mb', 'max_local_image_read_size_mb', 'max_local_audio_read_size_mb', 'max_local_video_read_size_mb', 'allowed_text_extensions']}
          fields={fields}
          values={values}
          onChange={onChange}
        />
        <ConfigSection title={t('capabilities:sections.commands')} fieldNames={['enable_read_file_command']} fields={fields} values={values} onChange={onChange} />
      </div>
    );
  }
  if (config.capability_id === 'http') {
    return (
      <div className="settings-config-sections">
        <p className="settings-helper-text">
          {t('capabilities:help.httpSettings')}
        </p>
        <ConfigSection
          title={t('capabilities:sections.networkAccess')}
          fieldNames={['enable_fetch_url_command', 'allowed_schemes', 'timeout_seconds', 'allow_redirects', 'max_redirects']}
          fields={fields}
          values={values}
          onChange={onChange}
        />
        <ConfigSection
          title={t('capabilities:sections.responseLimits')}
          fieldNames={['max_text_response_size_mb', 'max_image_response_size_mb']}
          fields={fields}
          values={values}
          onChange={onChange}
        />
      </div>
    );
  }
  if (config.capability_id === 'web_search') {
    return (
      <div className="settings-config-sections">
        <p className="settings-helper-text">
          {t('capabilities:help.webSearchSettings')}
        </p>
        <ConfigSection
          title={t('capabilities:sections.searchProvider')}
          fieldNames={['enable_web_search_command', 'searxng_base_url', 'timeout_seconds']}
          fields={fields}
          values={values}
          onChange={onChange}
        />
        <ConfigSection
          title={t('capabilities:sections.searchResults')}
          fieldNames={['max_results', 'language', 'safe_search']}
          fields={fields}
          values={values}
          onChange={onChange}
        />
        <WebSearchDiagnostics config={config} values={values} />
      </div>
    );
  }
  return (
    <ConfigForm
      fields={fields}
      values={values}
      onChange={onChange}
      emptyMessage={t('capabilities:empty.noConfigurableFields')}
    />
  );
}

function WebSearchDiagnostics({ config, values }: { config: CapabilityConfig; values: ConfigValues }) {
  const { t } = useTranslation(['capabilities']);
  const [query, setQuery] = useState(() => t('capabilities:diagnostics.defaultQuery'));
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<WebSearchTestResult | null>(null);

  async function runTest() {
    if (testing) return;
    setTesting(true);
    setResult(null);
    try {
      const response = await api.testWebSearch({
        query,
        config: buildUserConfig(config.config_schema || [], values),
      });
      setResult(response);
    } catch (error) {
      const message = error instanceof Error ? error.message : t('capabilities:diagnostics.errors.search_failed');
      setResult({
        ok: false,
        provider: 'searxng',
        base_url: '',
        query,
        elapsed_ms: 0,
        result_count: 0,
        first_result: null,
        sample_results: [],
        warnings: [],
        error_code: 'search_failed',
        error_message: message,
      });
    } finally {
      setTesting(false);
    }
  }

  const firstResult = result?.first_result || null;
  return (
    <section className="settings-config-section web-search-diagnostics">
      <div className="settings-section-heading-row">
        <h3>{t('capabilities:diagnostics.title')}</h3>
      </div>
      <label className="config-field settings-config-field" htmlFor="web-search-diagnostics-query">
        <span>{t('capabilities:diagnostics.query')}</span>
        <input
          id="web-search-diagnostics-query"
          type="text"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              void runTest();
            }
          }}
          placeholder={t('capabilities:diagnostics.queryPlaceholder')}
        />
      </label>
      <div className="settings-diagnostics-actions">
        <button className="settings-secondary-button" type="button" onClick={runTest} disabled={testing}>
          <Search size={14} />
          {testing ? t('capabilities:diagnostics.testing') : t('capabilities:diagnostics.testSearch')}
        </button>
      </div>
      {result ? (
        <div className={`settings-diagnostics-result ${result.ok ? 'success' : 'error'}`}>
          <div className="settings-diagnostics-status">
            <span className={`settings-badge ${result.ok ? 'success' : 'warning'}`}>
              {result.ok ? t('capabilities:diagnostics.connectionSuccessful') : webSearchErrorText(result, t)}
            </span>
          </div>
          {result.ok ? (
            <>
              <div className="settings-detail-grid compact">
                <InfoRow label={t('capabilities:diagnostics.provider')} value={result.provider} />
                <InfoRow label={t('capabilities:diagnostics.resultCount')} value={result.result_count} />
                <InfoRow label={t('capabilities:diagnostics.elapsedTime')} value={t('capabilities:diagnostics.elapsedMs', { count: result.elapsed_ms })} />
              </div>
              {firstResult ? (
                <div className="settings-diagnostics-first-result">
                  <span>{t('capabilities:diagnostics.firstResult')}</span>
                  <strong>{firstResult.title || firstResult.url}</strong>
                  <a href={firstResult.url} target="_blank" rel="noreferrer">
                    {firstResult.domain || firstResult.url}
                  </a>
                  {firstResult.snippet ? <p>{firstResult.snippet}</p> : null}
                </div>
              ) : (
                <div className="settings-empty-state compact">{t('capabilities:diagnostics.noResults')}</div>
              )}
            </>
          ) : null}
          {result.warnings.length ? (
            <div className="settings-diagnostics-warnings">
              <span>{t('capabilities:diagnostics.warnings')}</span>
              {result.warnings.map((warning) => (
                <code key={warning}>{warning}</code>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function webSearchErrorText(result: WebSearchTestResult, t: ReturnType<typeof useTranslation>['t']): string {
  const code = result.error_code || 'search_failed';
  const key = `capabilities:diagnostics.errors.${code}`;
  const translated = t(key);
  return translated === key ? result.error_message || t('capabilities:diagnostics.errors.search_failed') : translated;
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
  const { t } = useTranslation(['capabilities']);
  const sectionFields = fields.filter((field) => fieldNames.includes(field.name));
  if (!sectionFields.length) return null;
  return (
    <section className="settings-config-section">
      <h3>{title}</h3>
      <ConfigForm fields={sectionFields} values={values} onChange={onChange} emptyMessage={t('capabilities:empty.noFields')} />
    </section>
  );
}

function OverviewTab({ config, commandCount }: { config: CapabilityConfig; commandCount: number }) {
  const { t } = useTranslation(['capabilities']);
  const summary = config.manifest_summary;
  const configFieldCount = config.config_schema?.length ?? 0;
  const permissionHint = permissionHintText(summary.permissions, t);
  return (
    <div className="settings-detail-grid">
      <InfoRow label={t('capabilities:labels.description')} value={summary.description} wide />
      {permissionHint ? <InfoRow label={t('capabilities:labels.permissionHint')} value={permissionHint} wide /> : null}
      <InfoRow label={t('capabilities:labels.version')} value={(summary as { version?: string }).version} />
      <InfoRow label={t('capabilities:labels.exposedCommands')} value={commandCount} />
      <InfoRow label={t('capabilities:labels.configFields')} value={configFieldCount} />
      <InfoRow label={t('capabilities:labels.runtime')} value={config.capability_id === 'llm' ? t('capabilities:runtime.llm') : t('capabilities:runtime.localPython')} />
    </div>
  );
}

function permissionHintText(permissions: CapabilityConfig['manifest_summary']['permissions'], t: ReturnType<typeof useTranslation>['t']): string {
  if (!permissions) return '';
  const hints: string[] = [];
  if (permissions.filesystem?.read) hints.push(t('capabilities:permissions.filesystemRead'));
  if (permissions.network?.http) hints.push(t('capabilities:permissions.networkHttp'));
  return hints.join('; ');
}

function CommandsTab({ commands, capabilityEnabled }: { commands: Command[]; capabilityEnabled: boolean }) {
  const { t } = useTranslation(['capabilities', 'status']);
  if (!commands.length) {
    return <div className="settings-empty-state">{t('capabilities:empty.noCommands')}</div>;
  }
  return (
    <div className={`settings-table-wrap ${capabilityEnabled ? '' : 'disabled'}`}>
      <table className="settings-table">
        <thead>
          <tr>
            <th>{t('capabilities:labels.command')}</th>
            <th>{t('capabilities:labels.method')}</th>
            <th>{t('capabilities:labels.description')}</th>
            <th>{t('capabilities:labels.safe')}</th>
            <th>{t('capabilities:labels.confirm')}</th>
          </tr>
        </thead>
        <tbody>
          {commands.map((command) => (
            <tr key={command.name}>
              <td>
                <code>{command.name}</code>
              </td>
              <td>{command.method}</td>
              <td>{command.description || t('status:common.none')}</td>
              <td>
                <span className={`settings-badge ${command.safe ? 'success' : 'muted'}`}>{command.safe ? t('status:common.yes') : t('status:common.no')}</span>
              </td>
              <td>
                <span className={`settings-badge ${command.confirm ? 'warning' : 'muted'}`}>{command.confirm || t('status:common.no')}</span>
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
