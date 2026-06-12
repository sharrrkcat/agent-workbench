import { Brain, Clipboard, Eye, Hammer, Plus, Radio, RefreshCw, Save, Settings, Trash2, Zap } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../api/client';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { CapabilityConfig, LlmDefaults, LlmProfile, LlmProfileInput, LlmProviderModel, LlmProviderProfile, LlmProviderProfileInput, LlmResolvedConfig, LlmTestResult } from '../../types';
import { capabilitiesFromProfile, ModelCapabilityIcons } from '../ModelCapabilityIcons';
import { ConfigForm } from './ConfigForm';
import { SettingsApiError, toSettingsError, type SettingsErrorValue } from './SettingsApiError';
import { SettingsApiExampleBlock, formatApiExampleJson, type SettingsApiExample } from './SettingsApiExampleBlock';
import { SecretInput } from './SecretInput';
import { stableConfigString, type ConfigValues } from './configUtils';
import { ToggleSwitch } from './ToggleSwitch';

const providerOptions = ['openai_compatible', 'lm_studio', 'llama_cpp', 'custom', 'ollama', 'internal_transformers', 'internal_llama_cpp'] as const;
const llmProfileProviderOptions = ['openai_compatible', 'lm_studio', 'llama_cpp', 'custom', 'internal_transformers', 'internal_llama_cpp'] as const;
const internalProviderOptions = new Set<string>(['internal_transformers', 'internal_llama_cpp']);
const profileDefaults: LlmProfileInput = {
  alias: '',
  name: '',
  provider_profile_id: null,
  provider: 'openai_compatible',
  base_url: 'http://localhost:1234/v1',
  api_key: '',
  model_id: '',
  enabled: true,
  temperature: null,
  top_p: null,
  top_k: null,
  max_tokens: null,
  timeout: 60,
  supports_vision: false,
  supports_tools: false,
  supports_reasoning: false,
  supports_streaming: true,
  supports_json_mode: false,
  external_inference_enabled: false,
  notes: '',
};
const providerDefaults: LlmProviderProfileInput = {
  name: '',
  provider: 'openai_compatible',
  base_url: 'http://localhost:1234/v1',
  api_key: '',
  timeout_seconds: 60,
  enabled: true,
  metadata: {},
};
const internalProviderInstallCommands = {
  internal_transformers: [
    { key: 'basicCpu', command: 'uv pip install sentence-transformers transformers torch' },
    { key: 'cuda128', command: 'uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128\nuv pip install sentence-transformers transformers' },
  ],
  internal_llama_cpp: [
    { key: 'basicCpu', command: 'uv pip install llama-cpp-python' },
    { key: 'cuda128', command: 'CMAKE_ARGS="-DGGML_CUDA=on" uv pip install llama-cpp-python --force-reinstall --no-cache-dir' },
  ],
} as const;
const localRuntimeDeviceOptions = ['auto', 'cpu', 'cuda', 'mps'] as const;

function providerMetadata(draft: LlmProviderProfileInput): Record<string, unknown> {
  return { ...(draft.metadata || {}) };
}

function updateProviderMetadata(draft: LlmProviderProfileInput, values: Record<string, unknown>): LlmProviderProfileInput {
  return { ...draft, metadata: { ...providerMetadata(draft), ...values } };
}

function runtimeDeviceValue(draft: LlmProviderProfileInput): string {
  const value = String(providerMetadata(draft).local_runtime_device || 'auto');
  return localRuntimeDeviceOptions.includes(value as (typeof localRuntimeDeviceOptions)[number]) ? value : 'auto';
}

function gpuLayersValue(draft: LlmProviderProfileInput): number {
  const raw = providerMetadata(draft).llama_cpp_gpu_layers;
  const parsed = typeof raw === 'number' ? raw : Number.parseInt(String(raw ?? '0'), 10);
  return Number.isFinite(parsed) && parsed >= -1 ? parsed : 0;
}

export function LlmSettingsPanel({
  config,
  values,
  onValuesChange,
  showConfig = true,
  showProfiles = false,
  onBusyChange,
}: {
  config: CapabilityConfig;
  values: ConfigValues;
  onValuesChange: (values: ConfigValues) => void;
  showConfig?: boolean;
  showProfiles?: boolean;
  onBusyChange?: (busy: boolean) => void;
}) {
  const { t } = useTranslation(['llm', 'common', 'status']);
  const { testLlmConnection, testingLlm } = useWorkbenchStore();
  const [resolved, setResolved] = useState<LlmResolvedConfig | null>(null);
  const [testResult, setTestResult] = useState<LlmTestResult | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [resolvedError, setResolvedError] = useState<SettingsErrorValue | null>(null);
  const [modelListError, setModelListError] = useState<SettingsErrorValue | null>(null);
  const [testError, setTestError] = useState<SettingsErrorValue | null>(null);
  const [profiles, setProfiles] = useState<LlmProfile[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState('');
  const [profileDraft, setProfileDraft] = useState<LlmProfileInput>(profileDefaults);
  const [profileModels, setProfileModels] = useState<string[]>([]);
  const [profileError, setProfileError] = useState<SettingsErrorValue | null>(null);
  const [profileResult, setProfileResult] = useState<LlmTestResult | null>(null);
  const [profilesLoading, setProfilesLoading] = useState(false);
  const [profileBusy, setProfileBusy] = useState(false);
  const busy = testingLlm || loadingModels;
  const selectedProfile = profiles.find((profile) => profile.id === selectedProfileId);
  const profileDirty = useMemo(() => {
    const base = selectedProfile ? draftFromProfile(selectedProfile) : profileDefaults;
    return stableConfigString(cleanProfileInput(profileDraft)) !== stableConfigString(cleanProfileInput(base));
  }, [profileDraft, selectedProfile]);
  const hasEnvSource = useMemo(() => {
    const sources = resolved?.sources || {};
    return Object.values(sources).some((source) => String(source).toLowerCase().includes('env'));
  }, [resolved]);

  useEffect(() => {
    let cancelled = false;
    setResolvedError(null);
    void api.getResolvedLlmConfig().then((status) => {
      if (cancelled) return;
      setResolved(status);
      setResolvedError(null);
    }).catch((error) => {
      if (cancelled) return;
      setResolved(null);
      setResolvedError(toSettingsError(error, 'Failed to load resolved LLM config.'));
    });
    return () => {
      cancelled = true;
    };
  }, [config.updated_at]);

  useEffect(() => {
    if (showProfiles) void loadProfiles();
  }, [showProfiles]);

  useEffect(() => {
    if (selectedProfile) {
      setProfileDraft(draftFromProfile(selectedProfile));
    } else if (!selectedProfileId) {
      setProfileDraft(profileDefaults);
    }
    setProfileModels([]);
    setProfileResult(null);
    setProfileError(null);
  }, [selectedProfile, selectedProfileId]);

  useEffect(() => {
    onBusyChange?.(busy || (showProfiles && (profileBusy || profilesLoading)));
  }, [busy, onBusyChange, profileBusy, profilesLoading, showProfiles]);

  async function loadProfiles(nextSelectedId?: string) {
    setProfilesLoading(true);
    setProfileError(null);
    try {
      const loaded = await api.listLlmProfiles();
      setProfiles(loaded);
      if (nextSelectedId) {
        setSelectedProfileId(nextSelectedId);
      } else if (selectedProfileId && loaded.some((profile) => profile.id === selectedProfileId)) {
        setSelectedProfileId(selectedProfileId);
      } else if (loaded[0]) {
        setSelectedProfileId(loaded[0].id);
      } else {
        setSelectedProfileId('');
        setProfileDraft(profileDefaults);
      }
    } catch (error) {
      setProfileError(toSettingsError(error, 'Failed to load LLM profiles.'));
    } finally {
      setProfilesLoading(false);
    }
  }

  async function runTest() {
    setTestError(null);
    setTestResult(null);
    try {
      const result = await testLlmConnection();
      setTestResult(result);
      if (!result.success) {
        setTestError({ code: result.error_code || 'LLM_CONNECTION_FAILED', message: result.message });
      }
      if (result.models?.length) {
        setModels(result.models);
      }
    } catch (error) {
      setTestError(toSettingsError(error, 'LLM connection test failed.'));
    }
  }

  async function refreshModels() {
    setLoadingModels(true);
    setModelListError(null);
    try {
      const result = await api.listLlmModels();
      setModels(result.models.map((model) => model.id).filter(Boolean));
    } catch (error) {
      setModelListError(toSettingsError(error, 'Failed to list models.'));
    } finally {
      setLoadingModels(false);
    }
  }

  function startNewProfile() {
    setSelectedProfileId('');
    setProfileDraft(profileDefaults);
    setProfileModels([]);
    setProfileResult(null);
    setProfileError(null);
  }

  async function saveProfile() {
    setProfileBusy(true);
    setProfileError(null);
    try {
      const payload = cleanProfileInput(profileDraft);
      const saved = selectedProfile
        ? await api.patchLlmProfile(selectedProfile.id, payload)
        : await api.createLlmProfile(payload);
      await loadProfiles(saved.id);
    } catch (error) {
      setProfileError(toSettingsError(error, 'Failed to save LLM profile.'));
    } finally {
      setProfileBusy(false);
    }
  }

  async function deleteProfile() {
    if (!selectedProfile) return;
    if (!window.confirm(`Delete LLM profile "${selectedProfile.alias}"?`)) return;
    setProfileBusy(true);
    setProfileError(null);
    try {
      await api.deleteLlmProfile(selectedProfile.id);
      await loadProfiles('');
    } catch (error) {
      setProfileError(toSettingsError(error, 'Failed to delete LLM profile.'));
    } finally {
      setProfileBusy(false);
    }
  }

  async function testProfile() {
    if (!selectedProfile) return;
    setProfileBusy(true);
    setProfileResult(null);
    setProfileError(null);
    try {
      const result = await api.testLlmProfile(selectedProfile.id);
      setProfileResult(result);
      if (!result.success) {
        setProfileError({ code: result.error_code || 'LLM_CONNECTION_FAILED', message: result.message });
      }
      if (result.models?.length) setProfileModels(result.models);
    } catch (error) {
      setProfileError(toSettingsError(error, 'LLM profile connection test failed.'));
    } finally {
      setProfileBusy(false);
    }
  }

  async function refreshProfileModels() {
    if (!selectedProfile) return;
    setProfileBusy(true);
    setProfileError(null);
    try {
      const result = await api.listLlmProfileModels(selectedProfile.id);
      setProfileModels(result.models.map((model) => model.id).filter(Boolean));
    } catch (error) {
      setProfileError(toSettingsError(error, 'Failed to list profile models.'));
    } finally {
      setProfileBusy(false);
    }
  }

  return (
    <div className="llm-settings-panel">
      {showConfig ? (
        <section className="detail-section">
          <h3>{t('llm:sections.globalFallbackConfig')}</h3>
          <ConfigForm
            fields={config.config_schema || []}
            values={values}
            onChange={onValuesChange}
            emptyMessage={t('llm:empty.noConfigFields')}
          />
        </section>
      ) : null}

      <section className="detail-section">
        <div className="detail-section-heading">
          <h3>{t('llm:sections.resolvedConfig')}</h3>
          <button className="settings-secondary-button" type="button" onClick={() => void refreshModels()} disabled={loadingModels || testingLlm}>
            <RefreshCw size={14} className={loadingModels ? 'spin' : ''} />
            {loadingModels ? t('llm:actions.refreshing') : t('llm:actions.refreshModels')}
          </button>
        </div>
        {resolved ? <ResolvedLlmConfig status={resolved} /> : <div className="settings-empty-state">{t('llm:empty.resolvedUnavailable')}</div>}
        <p className="settings-warning-text">
          {hasEnvSource ? t('llm:help.environmentOverride') : t('llm:help.environmentOverride')}
        </p>
        {resolvedError ? <SettingsApiError error={resolvedError} /> : null}
        <div className="settings-button-row">
          <button className="settings-primary-button" type="button" disabled={testingLlm || loadingModels} onClick={() => void runTest()}>
            <Zap size={14} />
            {testingLlm ? t('llm:actions.testing') : t('llm:actions.testConnection')}
          </button>
        </div>
        {models.length ? (
          <label className="config-field settings-config-field" htmlFor="llm-model-select">
            <span>{t('llm:labels.availableModels')}</span>
            <select
              id="llm-model-select"
              value={String(values.model ?? '')}
              onChange={(event) => onValuesChange({ ...values, model: event.target.value })}
            >
              <option value="">{t('llm:empty.selectRefreshedModel')}</option>
              {models.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
            <small>{t('llm:help.chooseModelThenSave')}</small>
          </label>
        ) : null}
        {testResult ? (
          <p className={testResult.success ? 'settings-success-text' : 'settings-error-text'}>
            {testResult.message}
            {testResult.models?.length ? ` Models: ${testResult.models.join(', ')}` : ''}
          </p>
        ) : null}
        {testError ? <SettingsApiError error={testError} /> : null}
        {modelListError ? <SettingsApiError error={modelListError} /> : null}
      </section>

      {showProfiles ? (
      <section className="detail-section">
        <div className="detail-section-heading">
          <h3>{t('llm:sections.savedProfiles')}</h3>
          <button className="settings-secondary-button" type="button" onClick={startNewProfile} disabled={profileBusy}>
            <Plus size={14} />
            {t('llm:actions.newProfile')}
          </button>
        </div>
        <div className="llm-profile-layout">
          <div className="llm-profile-list">
            {profilesLoading ? <div className="settings-empty-state compact">{t('common:loading', { defaultValue: 'Loading...' })}</div> : null}
            {!profilesLoading && !profiles.length ? <div className="settings-empty-state compact">{t('llm:empty.noSavedProfiles')}</div> : null}
            {profiles.map((profile) => (
              <button
                key={profile.id}
                className={`llm-profile-row ${profile.id === selectedProfileId ? 'active' : ''} ${profile.enabled ? '' : 'disabled'}`}
                type="button"
                onClick={() => setSelectedProfileId(profile.id)}
              >
                <strong>{profile.name}</strong>
                <span>
                  <code>{profile.alias}</code> {profile.provider}
                </span>
                <small>{profile.model_id || t('llm:empty.noModelSelected')}</small>
                <ModelCapabilityIcons capabilities={capabilitiesFromProfile(profile)} className="settings-capability-icons" />
              </button>
            ))}
          </div>
          <div className="llm-profile-editor">
            <div className="llm-profile-editor-heading">
              <div>
                <strong>{selectedProfile ? selectedProfile.name : t('llm:actions.newProfile')}</strong>
                <span>{selectedProfile ? selectedProfile.alias : t('status:common.unset')}</span>
              </div>
              <ToggleSwitch
                checked={Boolean(profileDraft.enabled)}
                onChange={(enabled) => setProfileDraft({ ...profileDraft, enabled })}
                disabled={profileBusy}
              />
            </div>
            <ProfileForm
              draft={profileDraft}
              models={profileModels}
              onChange={setProfileDraft}
              disabled={profileBusy}
              hasApiKey={Boolean(selectedProfile?.api_key_set)}
            />
            <div className="settings-button-row">
              {profileDirty ? (
                <button className="settings-primary-button" type="button" onClick={() => void saveProfile()} disabled={profileBusy}>
                  <Save size={14} />
                  {profileBusy ? t('common:saving') : t('common:save')}
                </button>
              ) : null}
              {selectedProfile ? (
                <>
                  <button className="settings-secondary-button" type="button" onClick={() => void testProfile()} disabled={profileBusy}>
                    <Zap size={14} />
                    {t('llm:actions.testConnection')}
                  </button>
                  <button className="settings-secondary-button" type="button" onClick={() => void refreshProfileModels()} disabled={profileBusy}>
                    <RefreshCw size={14} className={profileBusy ? 'spin' : ''} />
                    {t('llm:actions.refreshModels')}
                  </button>
                  <button className="settings-secondary-button danger" type="button" onClick={() => void deleteProfile()} disabled={profileBusy}>
                    <Trash2 size={14} />
                    {t('common:delete')}
                  </button>
                </>
              ) : null}
            </div>
            {profileResult ? (
              <p className={profileResult.success ? 'settings-success-text' : 'settings-error-text'}>{profileResult.message}</p>
            ) : null}
            {profileError ? <SettingsApiError error={profileError} /> : null}
          </div>
        </div>
      </section>
      ) : null}
    </div>
  );
}

function ResolvedLlmConfig({ status }: { status: LlmResolvedConfig }) {
  const { t } = useTranslation(['llm', 'status']);
  return (
    <dl className="settings-definition-grid">
      <div>
        <dt>{t('llm:labels.source')}</dt>
        <dd>{status.source || t('status:common.unset')}</dd>
      </div>
      <div>
        <dt>{t('llm:labels.provider')}</dt>
        <dd>{status.provider || t('status:common.unset')}</dd>
      </div>
      <div>
        <dt>{t('llm:labels.baseUrl')}</dt>
        <dd>{status.base_url || t('status:common.unset')}</dd>
      </div>
      <div>
        <dt>{t('llm:labels.model')}</dt>
        <dd>{status.model || t('status:common.unset')}</dd>
      </div>
      <div>
        <dt>{t('llm:labels.timeout')}</dt>
        <dd>{status.timeout ?? t('status:common.unset')}</dd>
      </div>
      <div>
        <dt>{t('llm:labels.apiKeySet')}</dt>
        <dd>{status.api_key_set ? t('status:common.yes') : t('status:common.no')}</dd>
      </div>
    </dl>
  );
}

export function LlmDefaultsDetail({
  profiles,
  providerProfiles,
  onDirtyChange,
}: {
  profiles: LlmProfile[];
  providerProfiles: LlmProviderProfile[];
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation(['llm', 'common', 'status', 'settings']);
  return (
    <form className="settings-detail-form" onSubmit={(event) => event.preventDefault()}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">
            <Settings size={18} />
          </div>
          <div>
            <h2>{t('llm:labels.defaultModelProfile')}</h2>
            <p>{t('settings:llm.globalFallback', { ns: 'settings', defaultValue: 'Global fallback' })}</p>
          </div>
        </div>
      </header>
      <div className="settings-detail-body">
        <LlmDefaultModelProfileSection profiles={profiles} providerProfiles={providerProfiles} onDirtyChange={onDirtyChange} />
      </div>
    </form>
  );
}

export function LlmDefaultModelProfileSection({
  profiles,
  providerProfiles,
  onDirtyChange,
}: {
  profiles: LlmProfile[];
  providerProfiles: LlmProviderProfile[];
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation(['llm', 'common', 'status']);
  const [defaults, setDefaults] = useState<LlmDefaults | null>(null);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<SettingsErrorValue | null>(null);
  const dirty = Boolean(defaults && selected !== (defaults.default_model_profile_id || ''));
  const selectedProfile = profiles.find((profile) => profile.id === selected);
  const selectedProvider = providerProfiles.find((provider) => provider.id === selectedProfile?.provider_profile_id);

  useEffect(() => {
    let cancelled = false;
    void api.getLlmDefaults().then((loaded) => {
      if (cancelled) return;
      setDefaults(loaded);
      setSelected(loaded.default_model_profile_id || '');
    }).catch((caught) => setError(toSettingsError(caught, 'Failed to load LLM defaults.')));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    onDirtyChange(dirty);
    return () => onDirtyChange(false);
  }, [dirty, onDirtyChange]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const saved = await api.updateLlmDefaults({ default_model_profile_id: selected || null });
      setDefaults(saved);
      setSelected(saved.default_model_profile_id || '');
    } catch (caught) {
      setError(toSettingsError(caught, 'Failed to save default model profile.'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {error ? <SettingsApiError error={error} /> : null}
      <section className="detail-section">
        <div className="detail-section-heading">
          <h3>{t('llm:labels.defaultModelProfile')}</h3>
          {dirty ? (
            <button className="settings-primary-button" type="button" onClick={() => void save()} disabled={busy}>
              <Save size={14} />
              {busy ? t('common:saving') : t('common:save')}
            </button>
          ) : null}
        </div>
          <label className="config-field settings-config-field">
            <span>{t('llm:labels.defaultModelProfile')}</span>
            <select value={selected} onChange={(event) => setSelected(event.target.value)} disabled={busy}>
              <option value="">{t('status:common.none')} / {t('status:common.unset')}</option>
              {profiles.map((profile) => (
                <option key={profile.id} value={profile.id} disabled={!profile.enabled}>
                  {profile.name} ({profile.model_id || profile.alias}){profile.enabled ? '' : ` - ${t('status:common.disabled')}`}
                </option>
              ))}
            </select>
            <small>{t('llm:help.defaultModelProfileFallback')}</small>
          </label>
          {selectedProfile ? (
            <dl className="settings-definition-grid compact">
              <div>
                <dt>{t('llm:labels.providerProfile')}</dt>
                <dd>{selectedProvider?.name || t('llm:empty.missingProviderProfile')}</dd>
              </div>
              <div>
                <dt>{t('llm:labels.modelId')}</dt>
                <dd>{selectedProfile.model_id || t('status:common.unset')}</dd>
              </div>
              <div>
                <dt>{t('llm:labels.status')}</dt>
                <dd>{selectedProfile.enabled ? t('status:common.enabled') : t('status:common.disabled')}</dd>
              </div>
              <div>
                <dt>{t('llm:labels.capabilities')}</dt>
                <dd className="settings-definition-capabilities">
                  <DefaultProfileCapabilityIcons profile={selectedProfile} />
                </dd>
              </div>
            </dl>
          ) : (
            <div className="settings-empty-state compact">{t('llm:empty.noDefaultProfile')}</div>
          )}
      </section>
      <section className="detail-section">
        <h3>{t('llm:sections.advanced')}</h3>
        <p className="settings-muted-copy">
          {t('llm:help.legacyReadonly')}
        </p>
      </section>
    </>
  );
}

function DefaultProfileCapabilityIcons({ profile }: { profile: LlmProfile }) {
  const { t } = useTranslation('llm');
  const capabilities = capabilitiesFromProfile(profile);
  const hasCapabilities = capabilities.vision || capabilities.tools || capabilities.reasoning || capabilities.streaming;
  if (!hasCapabilities) return <span className="settings-muted-text">{t('empty.noCapabilities')}</span>;
  return <ModelCapabilityIcons capabilities={capabilities} className="settings-capability-icons" />;
}

export function LlmProviderProfileDetail({
  profiles,
  selectedProfileId,
  onProfilesChanged,
  onDirtyChange,
}: {
  profiles: LlmProviderProfile[];
  selectedProfileId: string;
  onProfilesChanged: (selectedProfileId?: string) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const selectedProfile = profiles.find((profile) => profile.id === selectedProfileId);
  const isNew = selectedProfileId === 'new';
  const { t } = useTranslation(['llm', 'common', 'settings', 'status']);
  const baseDraft = useMemo(() => selectedProfile ? providerDraftFromProfile(selectedProfile) : providerDefaults, [selectedProfile]);
  const baselineKey = stableConfigString(cleanProviderInput(baseDraft));
  const scopeId = isNew ? 'new' : selectedProfile?.id || '';
  const [draft, setDraft] = useState<LlmProviderProfileInput>(() => baseDraft);
  const [draftReady, setDraftReady] = useState(() => ({ scopeId, baselineKey }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<SettingsErrorValue | null>(null);
  const [result, setResult] = useState<LlmTestResult | null>(null);
  const [models, setModels] = useState<LlmProviderModel[]>([]);
  const providerKind = String(draft.provider || 'openai_compatible');
  const internalProvider = isInternalProvider(providerKind);

  useEffect(() => {
    setDraft(baseDraft);
    setDraftReady({ scopeId, baselineKey });
    setError(null);
    setResult(null);
    setModels([]);
  }, [baselineKey, baseDraft, scopeId, selectedProfileId]);

  const hydrated = draftReady.scopeId === scopeId && draftReady.baselineKey === baselineKey;
  const dirty = hydrated && stableConfigString(cleanProviderInput(draft)) !== baselineKey;

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  async function saveProvider() {
    setBusy(true);
    setError(null);
    try {
      const payload = cleanProviderInput(draft);
      if (!String(payload.name || '').trim()) throw new Error('Name is required.');
      const saved = selectedProfile ? await api.patchLlmProviderProfile(selectedProfile.id, payload) : await api.createLlmProviderProfile(payload);
      await onProfilesChanged(`provider:${saved.id}`);
    } catch (caught) {
      setError(toSettingsError(caught, 'Failed to save provider profile.'));
    } finally {
      setBusy(false);
    }
  }

  async function duplicateProvider() {
    if (!selectedProfile) return;
    setBusy(true);
    try {
      const saved = await api.duplicateLlmProviderProfile(selectedProfile.id);
      await onProfilesChanged(`provider:${saved.id}`);
    } catch (caught) {
      setError(toSettingsError(caught, 'Failed to duplicate provider profile.'));
    } finally {
      setBusy(false);
    }
  }

  async function deleteProvider() {
    if (!selectedProfile) return;
    if (!window.confirm(`Delete provider profile "${selectedProfile.name}"?`)) return;
    setBusy(true);
    try {
      await api.deleteLlmProviderProfile(selectedProfile.id);
      await onProfilesChanged('global');
    } catch (caught) {
      setError(toSettingsError(caught, 'Failed to delete provider profile.'));
    } finally {
      setBusy(false);
    }
  }

  async function testProvider() {
    if (!selectedProfile) return;
    setBusy(true);
    setResult(null);
    try {
      const testResult = await api.testLlmProviderProfile(selectedProfile.id);
      setResult(testResult);
    } catch (caught) {
      setError(toSettingsError(caught, 'Provider profile connection test failed.'));
    } finally {
      setBusy(false);
    }
  }

  async function refreshProviderModels() {
    if (!selectedProfile) return;
    setBusy(true);
    setError(null);
    try {
      const response = await api.listLlmProviderModels(selectedProfile.id);
      const modelItems = response.models.filter((model) => Boolean(model.id));
      setModels(modelItems);
      const chatModels = modelItems.filter((model) => isChatModel(model, providerKind));
      const message = internalProvider
        ? modelItems.length
          ? t('llm:results.foundModels', { count: modelItems.length })
          : t('llm:results.providerReturnedNoModels')
        : modelItems.length && !chatModels.length
        ? t('llm:results.providerReturnedNoChatModels')
        : modelItems.length
          ? t('llm:results.foundModels', { count: modelItems.length })
          : t('llm:results.providerReturnedNoModels');
      setResult({
        success: true,
        message,
        base_url: selectedProfile.base_url,
        models: modelItems.map((model) => model.id),
        warnings: response.warnings,
        backend: response.backend,
        models_root: response.models_root,
      });
    } catch (caught) {
      setError(toSettingsError(caught, 'Failed to refresh provider models.'));
    } finally {
      setBusy(false);
    }
  }

  async function copyProviderCommand(command: string) {
    try {
      await navigator.clipboard.writeText(command);
      setResult({ success: true, message: t('llm:results.commandCopied'), base_url: selectedProfile?.base_url || '' });
    } catch {
      setError({ code: 'COPY_FAILED', message: t('llm:errors.copyCommandFailed'), details: {} });
    }
  }

  if (!selectedProfile && !isNew) {
    return <div className="settings-placeholder"><h2>{t('settings:subsections.providerProfiles', { ns: 'settings', defaultValue: 'Provider Profile' })}</h2><p>{t('llm:empty.selectProviderProfile')}</p></div>;
  }

  return (
    <form className="settings-detail-form" onSubmit={(event) => event.preventDefault()}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">{profileInitials(String(draft.name || 'Provider'))}</div>
          <div>
            <h2>{String(draft.name || t('llm:actions.newProvider'))}</h2>
            <p><span>{providerDisplayLabel(t, providerKind)}</span></p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {dirty ? <button className="settings-primary-button" type="button" onClick={() => void saveProvider()} disabled={busy}><Save size={14} />{busy ? t('common:saving') : t('common:save')}</button> : null}
          {selectedProfile ? <button className="settings-secondary-button" type="button" onClick={() => void duplicateProvider()} disabled={busy}>{t('llm:actions.duplicate')}</button> : null}
          {selectedProfile ? <button className="settings-secondary-button danger" type="button" onClick={() => void deleteProvider()} disabled={busy}><Trash2 size={14} />{t('common:delete')}</button> : null}
          <ToggleSwitch checked={Boolean(draft.enabled)} onChange={(enabled) => setDraft({ ...draft, enabled })} disabled={busy} />
        </div>
      </header>
      <div className="settings-detail-body">
        {error ? <SettingsApiError error={error} /> : null}
        <section className="detail-section">
          <div className="detail-section-heading">
            <h3>{t('llm:sections.connection')}</h3>
            {selectedProfile ? (
              <div className="settings-button-row">
                <button className="settings-secondary-button" type="button" onClick={() => void testProvider()} disabled={busy}><Zap size={14} />{t('llm:actions.testConnection')}</button>
                <button className="settings-secondary-button" type="button" onClick={() => void refreshProviderModels()} disabled={busy}><RefreshCw size={14} className={busy ? 'spin' : ''} />{t('llm:actions.refreshModels')}</button>
              </div>
            ) : null}
          </div>
          <div className="settings-config-form llm-profile-form">
            <TextField label={t('llm:labels.name')} value={draft.name} onChange={(name) => setDraft({ ...draft, name })} disabled={busy} />
            <label className="config-field settings-config-field">
              <span>{t('llm:labels.provider')}</span>
              <select
                value={providerKind}
                onChange={(event) => {
                  const provider = event.target.value as LlmProviderProfileInput['provider'];
                  const nextMetadata = provider === 'internal_transformers'
                    ? { local_runtime_device: runtimeDeviceValue(draft) }
                    : provider === 'internal_llama_cpp'
                      ? { llama_cpp_gpu_layers: gpuLayersValue(draft) }
                      : {};
                  setDraft({
                    ...draft,
                    provider,
                    base_url: isInternalProvider(provider) ? '' : draft.base_url,
                    api_key: isInternalProvider(provider) ? '' : draft.api_key,
                    metadata: nextMetadata,
                  });
                }}
                disabled={busy}
              >
                {providerOptions.map((provider) => <option key={provider} value={provider}>{providerDisplayLabel(t, provider)}</option>)}
              </select>
            </label>
            {internalProvider ? (
              <>
                <NumberField label={t('llm:labels.timeout')} value={draft.timeout_seconds} onChange={(timeout_seconds) => setDraft({ ...draft, timeout_seconds })} disabled={busy} integer />
                <InternalProviderRuntimeSettings provider={providerKind} draft={draft} setDraft={setDraft} busy={busy} />
              </>
            ) : (
              <>
                <TextField label={t('llm:labels.baseUrl')} value={draft.base_url} onChange={(base_url) => setDraft({ ...draft, base_url })} disabled={busy} />
                <TextField label={t('llm:labels.apiKey')} value={draft.api_key} onChange={(api_key) => setDraft({ ...draft, api_key })} disabled={busy} secret hasSecret={Boolean(selectedProfile?.api_key_set)} />
                <NumberField label={t('llm:labels.timeout')} value={draft.timeout_seconds} onChange={(timeout_seconds) => setDraft({ ...draft, timeout_seconds })} disabled={busy} integer />
              </>
            )}
          </div>
          {result ? <p className={result.success ? 'settings-success-text' : 'settings-error-text'}>{result.message}</p> : null}
          {result?.warnings?.length ? <p className="settings-warning-text">{result.warnings.join(', ')}</p> : null}
          {models.length ? (
            <div className="settings-chip-row">
              {models.map((model) => <span key={model.id}>{internalProvider ? `${model.kind || model.type || 'model'}: ` : ''}{model.id}</span>)}
            </div>
          ) : null}
        </section>
        {internalProvider ? (
          <>
            <InternalProviderEnvironment
              provider={providerKind}
              backend={result?.backend}
              modelsRoot={result?.models_root}
            />
            <InternalProviderInstallCommands
              provider={providerKind}
              onCopyCommand={(command) => void copyProviderCommand(command)}
            />
          </>
        ) : null}
      </div>
    </form>
  );
}

function InternalProviderRuntimeSettings({
  provider,
  draft,
  setDraft,
  busy,
}: {
  provider: string;
  draft: LlmProviderProfileInput;
  setDraft: (draft: LlmProviderProfileInput) => void;
  busy: boolean;
}) {
  const { t } = useTranslation('llm');
  if (provider === 'internal_transformers') {
    return (
      <label className="config-field settings-config-field">
        <span>{t('llm:labels.runtimeDevice')}</span>
        <select
          value={runtimeDeviceValue(draft)}
          onChange={(event) => setDraft(updateProviderMetadata(draft, { local_runtime_device: event.target.value }))}
          disabled={busy}
        >
          {localRuntimeDeviceOptions.map((device) => <option key={device} value={device}>{t(`llm:runtimeDevices.${device}`)}</option>)}
        </select>
        <small>{t('llm:help.runtimeDevice')}</small>
      </label>
    );
  }
  if (provider === 'internal_llama_cpp') {
    return (
      <label className="config-field settings-config-field">
        <span>{t('llm:labels.gpuLayers')}</span>
        <input
          type="number"
          step={1}
          value={String(gpuLayersValue(draft))}
          onChange={(event) => {
            const raw = event.target.value;
            setDraft(updateProviderMetadata(draft, { llama_cpp_gpu_layers: raw === '' ? 0 : Number.parseInt(raw, 10) }));
          }}
          disabled={busy}
        />
        <small>{t('llm:help.gpuLayers')}</small>
      </label>
    );
  }
  return null;
}

function InternalProviderEnvironment({
  provider,
  backend,
  modelsRoot,
}: {
  provider: string;
  backend?: Record<string, unknown>;
  modelsRoot?: string;
}) {
  const { t } = useTranslation(['llm', 'status']);
  const dependencyKeys = provider === 'internal_llama_cpp'
    ? ['llama_cpp_available']
    : ['sentence_transformers_available', 'transformers_available', 'torch_available'];
  return (
    <section className="detail-section">
      <div className="detail-section-heading">
        <h3>{t('llm:sections.localModelEnvironment')}</h3>
      </div>
      <dl className="settings-definition-grid internal-provider-environment-grid">
        <div>
          <dt>{t('llm:labels.modelsRoot')}</dt>
          <dd>{modelsRoot || 'data/models'}</dd>
        </div>
        <div>
          <dt>{t('llm:labels.backend')}</dt>
          <dd>{formatInternalProviderStatus(backend?.available, t)}</dd>
        </div>
        {dependencyKeys.map((key) => (
          <div key={key}>
            <dt>{dependencyLabelKey(key)}</dt>
            <dd>{formatInternalProviderStatus(backend?.[key], t)}</dd>
          </div>
        ))}
        {'cuda_available' in (backend || {}) ? (
          <div>
            <dt>CUDA</dt>
            <dd>{formatInternalProviderStatus(backend?.cuda_available, t)}</dd>
          </div>
        ) : null}
        {'mps_available' in (backend || {}) ? (
          <div>
            <dt>MPS</dt>
            <dd>{formatInternalProviderStatus(backend?.mps_available, t)}</dd>
          </div>
        ) : null}
      </dl>
    </section>
  );
}

function InternalProviderInstallCommands({
  provider,
  onCopyCommand,
}: {
  provider: string;
  onCopyCommand: (command: string) => void;
}) {
  const { t } = useTranslation('llm');
  const commands = provider === 'internal_llama_cpp'
    ? internalProviderInstallCommands.internal_llama_cpp
    : internalProviderInstallCommands.internal_transformers;
  return (
    <section className="detail-section">
      <div className="detail-section-heading">
        <h3>{t('llm:install.title')}</h3>
      </div>
      {commands.map((item) => (
        <ProviderInstallCommand key={item.key} title={t(`llm:install.commands.${item.key}`)} command={item.command} onCopy={onCopyCommand} />
      ))}
    </section>
  );
}

function ProviderInstallCommand({ title, command, onCopy }: { title: string; command: string; onCopy: (command: string) => void }) {
  const { t } = useTranslation('llm');
  return (
    <div className="knowledge-command-card">
      <div className="knowledge-command-card-body">
        <strong>{title}</strong>
        <code>{command}</code>
      </div>
      <button className="settings-secondary-button" type="button" onClick={() => onCopy(command)}>
        <Clipboard size={14} />
        {t('actions.copyCommand')}
      </button>
    </div>
  );
}

function formatInternalProviderStatus(value: unknown, t: ReturnType<typeof useTranslation>['t']): string {
  if (value === true) return t('status:common.available');
  if (value === false) return t('status:common.unavailable');
  return t('status:common.unknown', { defaultValue: 'Unknown' });
}

function dependencyLabelKey(key: string): string {
  return key.replace(/_available$/, '').replace(/_/g, '-');
}

export function LlmProfileDetail({
  profiles,
  providerProfiles,
  selectedProfileId,
  onProfilesChanged,
  onDirtyChange,
}: {
  profiles: LlmProfile[];
  providerProfiles: LlmProviderProfile[];
  selectedProfileId: string;
  onProfilesChanged: (selectedProfileId?: string) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const selectedProfile = profiles.find((profile) => profile.id === selectedProfileId);
  const isNew = selectedProfileId === 'new';
  const { t } = useTranslation(['llm', 'common', 'settings']);
  const baseDraft = useMemo(() => selectedProfile ? draftFromProfile(selectedProfile) : profileDefaults, [selectedProfile]);
  const baselineKey = stableConfigString(cleanProfileInput(baseDraft));
  const scopeId = isNew ? 'new' : selectedProfile?.id || '';
  const [draft, setDraft] = useState<LlmProfileInput>(() => baseDraft);
  const [draftReady, setDraftReady] = useState(() => ({ scopeId, baselineKey }));
  const [keyTouched, setKeyTouched] = useState(false);
  const [models, setModels] = useState<LlmProviderModel[]>([]);
  const [selectedProviderModelId, setSelectedProviderModelId] = useState('');
  const [capabilitiesTouched, setCapabilitiesTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<SettingsErrorValue | null>(null);
  const [result, setResult] = useState<LlmTestResult | null>(null);

  useEffect(() => {
    setDraft(baseDraft);
    setDraftReady({ scopeId, baselineKey });
    setKeyTouched(false);
    setSelectedProviderModelId('');
    setCapabilitiesTouched(false);
    setModels([]);
    setBusy(false);
    setError(null);
    setResult(null);
  }, [baselineKey, baseDraft, scopeId, selectedProfileId]);

  const hydrated = draftReady.scopeId === scopeId && draftReady.baselineKey === baselineKey;
  const dirty = hydrated && stableConfigString(cleanProfileInput(draft)) !== baselineKey;
  const apiExampleModelId = draft.alias ? `llm:${draft.alias}` : 'llm:<profile_key>';
  const apiExamples: SettingsApiExample[] = [
    {
      id: 'chat-completions',
      title: t('settings:apiExamples.llm.chatCompletions'),
      body: formatApiExampleJson({
        model: apiExampleModelId,
        messages: [
          {
            role: 'user',
            content: 'Hello',
          },
        ],
      }),
    },
  ];

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  function updateDraft(patch: LlmProfileInput) {
    const next = { ...draft, ...patch };
    if (Object.prototype.hasOwnProperty.call(patch, 'name') && !keyTouched && isNew) {
      next.alias = uniqueProfileKey(String(patch.name || ''), profiles);
    }
    setDraft(next);
  }

  function updateCapabilityDraft(patch: LlmProfileInput) {
    setCapabilitiesTouched(true);
    updateDraft(patch);
  }

  async function saveProfile() {
    setBusy(true);
    setError(null);
    try {
      const payload = cleanProfileInput({
        ...draft,
        alias: draft.alias || uniqueProfileKey(String(draft.name || ''), profiles, selectedProfile?.id),
      });
      if (!String(payload.name || '').trim()) {
        throw new Error('Name is required.');
      }
      if (!String(payload.provider_profile_id || '').trim()) {
        throw new Error('Provider profile is required.');
      }
      if (!String(payload.model_id || '').trim()) {
        throw new Error('Model ID is required.');
      }
      const saved = selectedProfile
        ? await api.patchLlmProfile(selectedProfile.id, payload)
        : await api.createLlmProfile(payload);
      await onProfilesChanged(saved.id);
    } catch (caught) {
      setError(toSettingsError(caught, 'Failed to save LLM profile.'));
    } finally {
      setBusy(false);
    }
  }

  async function deleteProfile() {
    if (!selectedProfile) return;
    if (!window.confirm(`Delete LLM profile "${selectedProfile.name}"?`)) return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteLlmProfile(selectedProfile.id);
      await onProfilesChanged('global');
    } catch (caught) {
      setError(toSettingsError(caught, 'Failed to delete LLM profile.'));
    } finally {
      setBusy(false);
    }
  }

  async function duplicateProfile() {
    if (!selectedProfile) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await api.duplicateLlmProfile(selectedProfile.id);
      await onProfilesChanged(saved.id);
    } catch (caught) {
      setError(toSettingsError(caught, 'Failed to duplicate model profile.'));
    } finally {
      setBusy(false);
    }
  }

  async function testProfile() {
    if (!selectedProfile) return;
    setBusy(true);
    setResult(null);
    setError(null);
    try {
      const testResult = await api.testLlmProfile(selectedProfile.id);
      setResult(testResult);
      if (!testResult.success) {
        setError({ code: testResult.error_code || 'LLM_CONNECTION_FAILED', message: testResult.message });
      }
      if (testResult.models?.length) setModels(testResult.models.map((id) => ({ id })));
    } catch (caught) {
      setError(toSettingsError(caught, 'LLM profile connection test failed.'));
    } finally {
      setBusy(false);
    }
  }

  async function refreshProfileModels() {
    const providerId = String(draft.provider_profile_id || selectedProfile?.provider_profile_id || '');
    if (!providerId) return;
    setBusy(true);
    setError(null);
    try {
      const response = await api.listLlmProviderModels(providerId);
      const provider = providerProfiles.find((item) => item.id === providerId);
      const chatModels = response.models.filter((model) => Boolean(model.id) && isChatModel(model, provider?.provider));
      setModels(chatModels);
      setResult({
        success: true,
        message: response.models.length && !chatModels.length
          ? t('llm:results.providerReturnedNoChatModels')
          : chatModels.length
            ? t('llm:results.foundChatModels', { count: chatModels.length })
            : t('llm:results.providerReturnedNoModels'),
        base_url: providerProfileBaseUrl(providerId, providerProfiles),
        models: chatModels.map((model) => model.id),
      });
    } catch (caught) {
      setError(toSettingsError(caught, 'Failed to list profile models.'));
    } finally {
      setBusy(false);
    }
  }

  function selectProviderModel(modelId: string) {
    setSelectedProviderModelId(modelId);
    const model = models.find((item) => item.id === modelId);
    if (!model) return;
    const modelName = String(model.name || model.id);
    const next: LlmProfileInput = { model_id: model.id };
    const selectedProvider = providerProfiles.find((provider) => provider.id === draft.provider_profile_id);
    if (isInternalProvider(selectedProvider?.provider)) {
      next.supports_streaming = false;
      next.supports_vision = false;
      next.supports_tools = false;
    }
    if (!String(draft.name || '').trim()) {
      next.name = modelName;
      if (!keyTouched && isNew) {
        next.alias = uniqueProfileKey(modelName, profiles, selectedProfile?.id);
      }
    }
    if (!capabilitiesTouched && model.capabilities) {
      if (typeof model.capabilities.vision === 'boolean') next.supports_vision = model.capabilities.vision;
      if (typeof model.capabilities.tools === 'boolean') next.supports_tools = model.capabilities.tools;
      if (typeof model.capabilities.reasoning === 'boolean') next.supports_reasoning = model.capabilities.reasoning;
      if (typeof model.capabilities.json_mode === 'boolean') next.supports_json_mode = model.capabilities.json_mode;
    }
    updateDraft(next);
  }

  if (!selectedProfile && !isNew) {
    return <div className="settings-placeholder"><h2>{t('settings:subsections.modelProfiles')}</h2><p>{t('llm:empty.noModelSelected')}</p></div>;
  }

  return (
    <form className="settings-detail-form" onSubmit={(event) => event.preventDefault()}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">{profileInitials(String(draft.name || 'LLM'))}</div>
          <div>
            <h2>{String(draft.name || t('settings:objectList.newModel'))}</h2>
            <p>
              <code>{`key:${String(draft.alias || 'profile_key')}`}</code>
              <span>{providerProfileLabel(String(draft.provider_profile_id || ''), providerProfiles)}</span>
            </p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {dirty ? (
            <button className="settings-primary-button" type="button" onClick={() => void saveProfile()} disabled={busy}>
              <Save size={14} />
              {busy ? t('common:saving') : t('common:save')}
            </button>
          ) : null}
          {selectedProfile ? (
            <button className="settings-secondary-button" type="button" onClick={() => void duplicateProfile()} disabled={busy}>
              {t('llm:actions.duplicate')}
            </button>
          ) : null}
          {selectedProfile ? (
            <button className="settings-secondary-button danger" type="button" onClick={() => void deleteProfile()} disabled={busy}>
              <Trash2 size={14} />
              {t('common:delete')}
            </button>
          ) : null}
          <ToggleSwitch checked={Boolean(draft.enabled)} onChange={(enabled) => updateDraft({ enabled })} disabled={busy} />
        </div>
      </header>
      <div className="settings-detail-body">
        {error ? <SettingsApiError error={error} /> : null}
        <section className="detail-section">
          <div className="detail-section-heading">
            <h3>{t('llm:sections.model')}</h3>
            <div className="settings-button-row">
              <button className="settings-secondary-button" type="button" onClick={() => void refreshProfileModels()} disabled={busy || !draft.provider_profile_id}>
                <RefreshCw size={14} className={busy ? 'spin' : ''} />
                {t('llm:actions.refreshModels')}
              </button>
            </div>
          </div>
          <div className="settings-config-form llm-profile-form">
            <TextField label={t('llm:labels.name')} value={draft.name} onChange={(name) => updateDraft({ name })} disabled={busy} />
            <label className="config-field settings-config-field">
              <span>{t('llm:labels.providerProfile')}</span>
              <select
                value={String(draft.provider_profile_id || '')}
                onChange={(event) => {
                  const provider = providerProfiles.find((item) => item.id === event.target.value);
                  updateDraft({
                    provider_profile_id: event.target.value || null,
                    model_id: isInternalProvider(provider?.provider) ? '' : draft.model_id,
                    supports_streaming: isInternalProvider(provider?.provider) ? false : draft.supports_streaming,
                    supports_vision: isInternalProvider(provider?.provider) ? false : draft.supports_vision,
                    supports_tools: isInternalProvider(provider?.provider) ? false : draft.supports_tools,
                  });
                  setModels([]);
                  setSelectedProviderModelId('');
                }}
                disabled={busy}
              >
                <option value="">{t('llm:empty.selectProviderProfile')}</option>
                {providerProfiles.map((provider) => (
                  <option key={provider.id} value={provider.id} disabled={!provider.enabled}>
                    {provider.name}{provider.enabled ? '' : ` - ${t('status:common.disabled', { ns: 'status', defaultValue: 'disabled' })}`}
                  </option>
                ))}
              </select>
            </label>
            <label className="config-field settings-config-field">
              <span>{t('llm:labels.chooseFromProvider')}</span>
              <select value={selectedProviderModelId} onChange={(event) => selectProviderModel(event.target.value)} disabled={busy || !models.length}>
                <option value="">{models.length ? t('llm:empty.selectRefreshedModel') : t('llm:empty.noRefreshedModels')}</option>
                {models.map((model) => <option key={model.id} value={model.id} title={model.id}>{modelOptionLabel(model)}</option>)}
              </select>
            </label>
            <label className="config-field settings-config-field">
              <span>{t('llm:labels.manualModelIdOverride')}</span>
              <input type="text" value={String(draft.model_id ?? '')} onChange={(event) => updateDraft({ model_id: event.target.value })} disabled={busy} />
            </label>
            <TextField label={t('llm:labels.notes')} value={draft.notes} onChange={(notes) => updateDraft({ notes })} disabled={busy} textarea />
            <label className="config-field settings-config-field boolean-field">
              <span>{t('settings:externalInference.enabled')}</span>
              <ToggleSwitch checked={Boolean(draft.external_inference_enabled)} onChange={(external_inference_enabled) => updateDraft({ external_inference_enabled })} disabled={busy} />
              <small>{t('settings:externalInference.help')}</small>
            </label>
          </div>
          {result ? <p className={result.success ? 'settings-success-text' : 'settings-error-text'}>{result.message}</p> : null}
        </section>
        <section className="detail-section">
          <h3>{t('llm:sections.generationDefaults')}</h3>
          <div className="settings-config-form llm-profile-form">
            <NumberField label={t('llm:labels.temperature')} value={draft.temperature} onChange={(temperature) => updateDraft({ temperature })} disabled={busy} />
            <NumberField label={t('llm:labels.topP')} value={draft.top_p} onChange={(top_p) => updateDraft({ top_p })} disabled={busy} />
            <NumberField label={t('llm:labels.topK')} value={draft.top_k} onChange={(top_k) => updateDraft({ top_k })} disabled={busy} integer />
            <NumberField label={t('llm:labels.maxTokens')} value={draft.max_tokens} onChange={(max_tokens) => updateDraft({ max_tokens })} disabled={busy} integer />
          </div>
        </section>
        <section className="detail-section">
          <h3>{t('llm:sections.capabilities')}</h3>
          <p className="settings-muted-copy">
            {t('llm:help.reasoningOutput')}
          </p>
          <div className="llm-profile-flags">
            <ToggleSwitch checked={Boolean(draft.supports_vision)} onChange={(supports_vision) => updateCapabilityDraft({ supports_vision })} label={<CapabilityToggleLabel kind="vision" label={t('llm:labels.vision')} />} disabled={busy} />
            <ToggleSwitch checked={Boolean(draft.supports_tools)} onChange={(supports_tools) => updateCapabilityDraft({ supports_tools })} label={<CapabilityToggleLabel kind="tools" label={t('llm:labels.tools')} />} disabled={busy} />
            <ToggleSwitch checked={Boolean(draft.supports_reasoning)} onChange={(supports_reasoning) => updateCapabilityDraft({ supports_reasoning })} label={<CapabilityToggleLabel kind="reasoning" label={t('llm:labels.reasoningOutput')} />} disabled={busy} />
            <ToggleSwitch checked={Boolean(draft.supports_streaming)} onChange={(supports_streaming) => updateCapabilityDraft({ supports_streaming })} label={<CapabilityToggleLabel kind="streaming" label={t('llm:labels.streaming')} />} disabled={busy} />
          </div>
        </section>
        <section className="detail-section">
          <h3>{t('llm:sections.advanced')}</h3>
          <div className="settings-config-form llm-profile-form">
            <label className="config-field settings-config-field">
              <span>{t('llm:labels.profileKey')}</span>
              <input
                type="text"
                value={String(draft.alias ?? '')}
                onChange={(event) => {
                  setKeyTouched(true);
                  updateDraft({ alias: sanitizeProfileKey(event.target.value) });
                }}
                disabled={busy}
              />
              <small>{t('llm:help.profileKey')}</small>
            </label>
          </div>
        </section>
        <SettingsApiExampleBlock
          endpoint="/v1/chat/completions"
          modelId={apiExampleModelId}
          modelIdHelp={t('settings:apiExamples.modelIdHelp')}
          examples={apiExamples}
        />
      </div>
    </form>
  );
}

function CapabilityToggleLabel({ kind, label }: { kind: 'vision' | 'tools' | 'reasoning' | 'streaming'; label: string }) {
  const Icon = kind === 'vision' ? Eye : kind === 'tools' ? Hammer : kind === 'reasoning' ? Brain : Radio;
  return (
    <span className={`capability-toggle-label ${kind}`}>
      <Icon size={13} aria-hidden="true" />
      {label}
    </span>
  );
}

function ProfileForm({
  draft,
  models,
  onChange,
  disabled,
  hasApiKey,
}: {
  draft: LlmProfileInput;
  models: string[];
  onChange: (draft: LlmProfileInput) => void;
  disabled: boolean;
  hasApiKey: boolean;
}) {
  const set = (key: keyof LlmProfileInput, value: unknown) => onChange({ ...draft, [key]: value });
  return (
    <div className="settings-config-form llm-profile-form">
      <TextField label="Alias" value={draft.alias} onChange={(value) => set('alias', value)} disabled={disabled} />
      <TextField label="Name" value={draft.name} onChange={(value) => set('name', value)} disabled={disabled} />
      <label className="config-field settings-config-field">
        <span>Provider</span>
        <select value={draft.provider || 'openai_compatible'} onChange={(event) => set('provider', event.target.value)} disabled={disabled}>
          {llmProfileProviderOptions.map((provider) => (
            <option key={provider} value={provider}>
              {provider}
            </option>
          ))}
        </select>
      </label>
      <TextField label="Base URL" value={draft.base_url} onChange={(value) => set('base_url', value)} disabled={disabled} />
      <TextField
        label="API key"
        value={draft.api_key}
        onChange={(value) => set('api_key', value)}
        disabled={disabled}
        secret
        hasSecret={hasApiKey}
      />
      <label className="config-field settings-config-field">
        <span>Model ID</span>
        <input type="text" value={String(draft.model_id ?? '')} onChange={(event) => set('model_id', event.target.value)} disabled={disabled} />
        {models.length ? (
          <select value={String(draft.model_id ?? '')} onChange={(event) => set('model_id', event.target.value)} disabled={disabled}>
            <option value="">Select refreshed model</option>
            {models.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))}
          </select>
        ) : null}
      </label>
      <NumberField label="Temperature" value={draft.temperature} onChange={(value) => set('temperature', value)} disabled={disabled} />
      <NumberField label="Top P" value={draft.top_p} onChange={(value) => set('top_p', value)} disabled={disabled} />
      <NumberField label="Top K" value={draft.top_k} onChange={(value) => set('top_k', value)} disabled={disabled} integer />
      <NumberField label="Max tokens" value={draft.max_tokens} onChange={(value) => set('max_tokens', value)} disabled={disabled} integer />
      <NumberField label="Timeout" value={draft.timeout} onChange={(value) => set('timeout', value)} disabled={disabled} integer />
      <TextField label="Notes" value={draft.notes} onChange={(value) => set('notes', value)} disabled={disabled} textarea />
      <div className="llm-profile-flags">
        <ToggleSwitch checked={Boolean(draft.supports_vision)} onChange={(value) => set('supports_vision', value)} label={<CapabilityToggleLabel kind="vision" label="Vision" />} disabled={disabled} />
        <ToggleSwitch checked={Boolean(draft.supports_tools)} onChange={(value) => set('supports_tools', value)} label={<CapabilityToggleLabel kind="tools" label="Tools" />} disabled={disabled} />
        <ToggleSwitch checked={Boolean(draft.supports_reasoning)} onChange={(value) => set('supports_reasoning', value)} label={<CapabilityToggleLabel kind="reasoning" label="Reasoning output" />} disabled={disabled} />
        <ToggleSwitch checked={Boolean(draft.supports_streaming)} onChange={(value) => set('supports_streaming', value)} label={<CapabilityToggleLabel kind="streaming" label="Streaming" />} disabled={disabled} />
      </div>
    </div>
  );
}

function TextField({
  label,
  value,
  onChange,
  disabled,
  secret = false,
  textarea = false,
  hasSecret = false,
}: {
  label: string;
  value: unknown;
  onChange: (value: string) => void;
  disabled: boolean;
  secret?: boolean;
  textarea?: boolean;
  hasSecret?: boolean;
}) {
  if (secret) {
    return (
      <SecretInput
        label={label}
        value={String(value ?? '')}
        onChange={onChange}
        hasSecret={hasSecret}
        disabled={disabled}
      />
    );
  }
  return (
    <label className="config-field settings-config-field">
      <span>{label}</span>
      {textarea ? (
        <textarea value={String(value ?? '')} onChange={(event) => onChange(event.target.value)} disabled={disabled} />
      ) : (
        <input
          type="text"
          value={String(value ?? '')}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
        />
      )}
    </label>
  );
}

function NumberField({
  label,
  value,
  onChange,
  disabled,
  integer = false,
}: {
  label: string;
  value: unknown;
  onChange: (value: number | null) => void;
  disabled: boolean;
  integer?: boolean;
}) {
  return (
    <label className="config-field settings-config-field">
      <span>{label}</span>
      <input
        type="number"
        step={integer ? 1 : 'any'}
        value={value === null || value === undefined ? '' : String(value)}
        onChange={(event) => {
          const raw = event.target.value;
          onChange(raw === '' ? null : integer ? Number.parseInt(raw, 10) : Number(raw));
        }}
        disabled={disabled}
      />
    </label>
  );
}

function draftFromProfile(profile: LlmProfile): LlmProfileInput {
  return {
    alias: profile.alias,
    name: profile.name,
    provider_profile_id: profile.provider_profile_id || null,
    provider: profile.provider,
    base_url: profile.base_url,
    api_key: '',
    model_id: profile.model_id,
    enabled: profile.enabled,
    temperature: profile.temperature ?? null,
    top_p: profile.top_p ?? null,
    top_k: profile.top_k ?? null,
    max_tokens: profile.max_tokens ?? null,
    timeout: profile.timeout ?? null,
    supports_vision: Boolean(profile.supports_vision),
    supports_tools: Boolean(profile.supports_tools),
    supports_reasoning: Boolean(profile.supports_reasoning),
    supports_streaming: Boolean(profile.supports_streaming),
    supports_json_mode: Boolean(profile.supports_json_mode),
    external_inference_enabled: Boolean(profile.external_inference_enabled),
    notes: profile.notes || '',
  };
}

function providerDraftFromProfile(profile: LlmProviderProfile): LlmProviderProfileInput {
  return {
    name: profile.name,
    provider: profile.provider,
    base_url: profile.base_url,
    api_key: '',
    timeout_seconds: profile.timeout_seconds ?? null,
    enabled: profile.enabled,
    metadata: profile.metadata || {},
  };
}

function capabilitiesFromDraft(draft: LlmProfileInput) {
  return {
    vision: Boolean(draft.supports_vision),
    tools: Boolean(draft.supports_tools),
    reasoning: Boolean(draft.supports_reasoning),
    streaming: Boolean(draft.supports_streaming),
  };
}

function cleanProfileInput(input: LlmProfileInput): LlmProfileInput {
  const entries = Object.entries(input).filter(([key, value]) => {
    if (value === undefined) return false;
    if (key === 'api_key' && String(value || '').trim() === '') return false;
    return true;
  });
  return Object.fromEntries(entries) as LlmProfileInput;
}

function cleanProviderInput(input: LlmProviderProfileInput): LlmProviderProfileInput {
  const normalized: LlmProviderProfileInput = { ...input };
  if (normalized.provider === 'internal_transformers') {
    normalized.metadata = { local_runtime_device: runtimeDeviceValue(normalized) };
  } else if (normalized.provider === 'internal_llama_cpp') {
    normalized.metadata = { llama_cpp_gpu_layers: gpuLayersValue(normalized) };
  }
  const entries = Object.entries(normalized).filter(([key, value]) => {
    if (value === undefined) return false;
    if (key === 'api_key' && String(value || '').trim() === '') return false;
    return true;
  });
  return Object.fromEntries(entries) as LlmProviderProfileInput;
}

function providerProfileLabel(providerProfileId: string, providers: LlmProviderProfile[]): string {
  if (!providerProfileId) return 'Missing provider profile';
  const provider = providers.find((item) => item.id === providerProfileId);
  return provider ? provider.name : 'Missing provider profile';
}

function providerProfileBaseUrl(providerProfileId: string, providers: LlmProviderProfile[]): string {
  return providers.find((item) => item.id === providerProfileId)?.base_url || '';
}

function isChatModel(model: LlmProviderModel, provider?: string): boolean {
  if (isInternalProvider(provider)) {
    if (provider === 'internal_llama_cpp' && isLlamaCppAuxiliaryModel(model.id)) {
      return false;
    }
    return String(model.kind || model.type || model.id || '').toLowerCase() === 'llm' || String(model.id || '').startsWith('llm/');
  }
  const kind = String(model.kind || model.type || 'unknown').toLowerCase();
  return kind !== 'embedding' && kind !== 'reranker';
}

function isLlamaCppAuxiliaryModel(modelId: string | undefined): boolean {
  const basename = String(modelId || '').split('/').pop()?.toLowerCase() || '';
  return (
    basename.startsWith('mmproj') ||
    basename.includes('mmproj') ||
    basename.includes('projector') ||
    basename.includes('vision-projector')
  );
}

function isInternalProvider(provider: string | undefined | null): boolean {
  return internalProviderOptions.has(String(provider || ''));
}

function providerDisplayLabel(t: (key: string, options?: Record<string, unknown>) => string, provider: string): string {
  return t(`llm:providers.${provider}`, { defaultValue: provider });
}

function providerHelperText(providerProfileId: string | undefined | null, providers: LlmProviderProfile[]) {
  const provider = providers.find((item) => item.id === providerProfileId);
  if (provider?.provider === 'llama_cpp') {
    return <ProviderHelperText translationKey="llm:help.llamaCppProviderModelList" />;
  }
  if (isInternalProvider(provider?.provider)) {
    return <ProviderHelperText translationKey="llm:help.internalLlmProfilesOnly" />;
  }
  return null;
}

function ProviderHelperText({ translationKey }: { translationKey: string }) {
  const { t } = useTranslation('llm');
  return <small>{t(translationKey)}</small>;
}

function modelOptionLabel(model: LlmProviderModel): string {
  const name = String(model.name || model.display_name || '').trim();
  const id = String(model.id || '').trim();
  return name && name !== id ? `${name} (${id})` : id;
}

export function sanitizeProfileKey(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '_')
    .replace(/[^a-zA-Z0-9_-]/g, '')
    .replace(/_+/g, '_')
    .replace(/-+/g, '-');
}

export function uniqueProfileKey(name: string, profiles: LlmProfile[], currentProfileId?: string): string {
  const base = sanitizeProfileKey(name) || 'profile';
  const existing = new Set(
    profiles
      .filter((profile) => profile.id !== currentProfileId)
      .map((profile) => profile.alias),
  );
  if (!existing.has(base)) return base;
  let index = 2;
  while (existing.has(`${base}_${index}`)) {
    index += 1;
  }
  return `${base}_${index}`;
}

function profileInitials(value: string): string {
  return value
    .replace(/[/_-]/g, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase())
    .join('');
}
