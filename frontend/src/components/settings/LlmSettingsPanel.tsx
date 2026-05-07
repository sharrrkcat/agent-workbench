import { Brain, Eye, Hammer, Plus, Radio, RefreshCw, Save, Settings, Trash2, Zap } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { CapabilityConfig, LlmDefaults, LlmProfile, LlmProfileInput, LlmProviderProfile, LlmProviderProfileInput, LlmResolvedConfig, LlmTestResult } from '../../types';
import { capabilitiesFromProfile, ModelCapabilityIcons } from '../ModelCapabilityIcons';
import { ConfigForm } from './ConfigForm';
import { SettingsApiError, toSettingsError, type SettingsErrorValue } from './SettingsApiError';
import { SecretInput } from './SecretInput';
import { stableConfigString, type ConfigValues } from './configUtils';
import { ToggleSwitch } from './ToggleSwitch';

const providerOptions = ['openai_compatible', 'lm_studio', 'llama_cpp', 'custom'] as const;
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
          <h3>Global fallback config</h3>
          <ConfigForm
            fields={config.config_schema || []}
            values={values}
            onChange={onValuesChange}
            emptyMessage="This capability has no configurable fields."
          />
        </section>
      ) : null}

      <section className="detail-section">
        <div className="detail-section-heading">
          <h3>Resolved LLM config</h3>
          <button className="settings-secondary-button" type="button" onClick={() => void refreshModels()} disabled={loadingModels || testingLlm}>
            <RefreshCw size={14} className={loadingModels ? 'spin' : ''} />
            {loadingModels ? 'Refreshing...' : 'Refresh models'}
          </button>
        </div>
        {resolved ? <ResolvedLlmConfig status={resolved} /> : <div className="settings-empty-state">Resolved config is unavailable.</div>}
        <p className="settings-warning-text">
          {hasEnvSource ? 'Environment variables may override saved settings.' : 'Environment variables may override saved settings.'}
        </p>
        {resolvedError ? <SettingsApiError error={resolvedError} /> : null}
        <div className="settings-button-row">
          <button className="settings-primary-button" type="button" disabled={testingLlm || loadingModels} onClick={() => void runTest()}>
            <Zap size={14} />
            {testingLlm ? 'Testing...' : 'Test connection'}
          </button>
        </div>
        {models.length ? (
          <label className="config-field settings-config-field" htmlFor="llm-model-select">
            <span>Available models</span>
            <select
              id="llm-model-select"
              value={String(values.model ?? '')}
              onChange={(event) => onValuesChange({ ...values, model: event.target.value })}
            >
              <option value="">Select model</option>
              {models.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
            <small>Choose a model, then Save to store it in the LLM capability config.</small>
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
          <h3>Saved LLM Profiles</h3>
          <button className="settings-secondary-button" type="button" onClick={startNewProfile} disabled={profileBusy}>
            <Plus size={14} />
            New profile
          </button>
        </div>
        <div className="llm-profile-layout">
          <div className="llm-profile-list">
            {profilesLoading ? <div className="settings-empty-state compact">Loading profiles...</div> : null}
            {!profilesLoading && !profiles.length ? <div className="settings-empty-state compact">No saved profiles.</div> : null}
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
                <small>{profile.model_id || 'No model selected'}</small>
                <ModelCapabilityIcons capabilities={capabilitiesFromProfile(profile)} className="settings-capability-icons" />
              </button>
            ))}
          </div>
          <div className="llm-profile-editor">
            <div className="llm-profile-editor-heading">
              <div>
                <strong>{selectedProfile ? selectedProfile.name : 'New profile'}</strong>
                <span>{selectedProfile ? selectedProfile.alias : 'Unsaved'}</span>
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
                  {profileBusy ? 'Saving...' : 'Save'}
                </button>
              ) : null}
              {selectedProfile ? (
                <>
                  <button className="settings-secondary-button" type="button" onClick={() => void testProfile()} disabled={profileBusy}>
                    <Zap size={14} />
                    Test connection
                  </button>
                  <button className="settings-secondary-button" type="button" onClick={() => void refreshProfileModels()} disabled={profileBusy}>
                    <RefreshCw size={14} className={profileBusy ? 'spin' : ''} />
                    Refresh models
                  </button>
                  <button className="settings-secondary-button danger" type="button" onClick={() => void deleteProfile()} disabled={profileBusy}>
                    <Trash2 size={14} />
                    Delete
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
  return (
    <dl className="settings-definition-grid">
      <div>
        <dt>Source</dt>
        <dd>{status.source || 'unset'}</dd>
      </div>
      <div>
        <dt>Provider</dt>
        <dd>{status.provider || 'unset'}</dd>
      </div>
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
        <dt>API key set</dt>
        <dd>{status.api_key_set ? 'yes' : 'no'}</dd>
      </div>
    </dl>
  );
}

export function LlmDefaultsDetail({
  profiles,
  onDirtyChange,
}: {
  profiles: LlmProfile[];
  onDirtyChange: (dirty: boolean) => void;
}) {
  const [defaults, setDefaults] = useState<LlmDefaults | null>(null);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<SettingsErrorValue | null>(null);
  const dirty = Boolean(defaults && selected !== (defaults.default_model_profile_id || ''));

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
    <form className="settings-detail-form" onSubmit={(event) => event.preventDefault()}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">
            <Settings size={18} />
          </div>
          <div>
            <h2>Default model profile</h2>
            <p>Global fallback model</p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {dirty ? (
            <button className="settings-primary-button" type="button" onClick={() => void save()} disabled={busy}>
              <Save size={14} />
              {busy ? 'Saving...' : 'Save'}
            </button>
          ) : null}
        </div>
      </header>
      <div className="settings-detail-body">
        {error ? <SettingsApiError error={error} /> : null}
        <section className="detail-section">
          <h3>Defaults</h3>
          <label className="config-field settings-config-field">
            <span>Default model profile</span>
            <select value={selected} onChange={(event) => setSelected(event.target.value)} disabled={busy}>
              <option value="">Legacy fallback / environment</option>
              {profiles.map((profile) => (
                <option key={profile.id} value={profile.id} disabled={!profile.enabled}>
                  {profile.name} ({profile.model_id || profile.alias}){profile.enabled ? '' : ' - disabled'}
                </option>
              ))}
            </select>
            <small>Legacy fallback is used only when no model profile is resolved.</small>
          </label>
        </section>
      </div>
    </form>
  );
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
  const [draft, setDraft] = useState<LlmProviderProfileInput>(() => (selectedProfile ? providerDraftFromProfile(selectedProfile) : providerDefaults));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<SettingsErrorValue | null>(null);
  const [result, setResult] = useState<LlmTestResult | null>(null);

  useEffect(() => {
    setDraft(selectedProfile ? providerDraftFromProfile(selectedProfile) : providerDefaults);
    setError(null);
    setResult(null);
  }, [selectedProfile, selectedProfileId]);

  const baseDraft = selectedProfile ? providerDraftFromProfile(selectedProfile) : providerDefaults;
  const dirty = stableConfigString(cleanProviderInput(draft)) !== stableConfigString(cleanProviderInput(baseDraft));

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

  if (!selectedProfile && !isNew) {
    return <div className="settings-placeholder"><h2>Provider Profile</h2><p>Select a provider profile or create a new one.</p></div>;
  }

  return (
    <form className="settings-detail-form" onSubmit={(event) => event.preventDefault()}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">{profileInitials(String(draft.name || 'Provider'))}</div>
          <div>
            <h2>{String(draft.name || 'New provider')}</h2>
            <p><span>{String(draft.provider || 'openai_compatible')}</span></p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {dirty ? <button className="settings-primary-button" type="button" onClick={() => void saveProvider()} disabled={busy}><Save size={14} />{busy ? 'Saving...' : 'Save'}</button> : null}
          {selectedProfile ? <button className="settings-secondary-button" type="button" onClick={() => void duplicateProvider()} disabled={busy}>Duplicate</button> : null}
          {selectedProfile ? <button className="settings-secondary-button danger" type="button" onClick={() => void deleteProvider()} disabled={busy}><Trash2 size={14} />Delete</button> : null}
          <ToggleSwitch checked={Boolean(draft.enabled)} onChange={(enabled) => setDraft({ ...draft, enabled })} disabled={busy} />
        </div>
      </header>
      <div className="settings-detail-body">
        {error ? <SettingsApiError error={error} /> : null}
        <section className="detail-section">
          <div className="detail-section-heading">
            <h3>Connection</h3>
            {selectedProfile ? <button className="settings-secondary-button" type="button" onClick={() => void testProvider()} disabled={busy}><Zap size={14} />Test connection</button> : null}
          </div>
          <div className="settings-config-form llm-profile-form">
            <TextField label="Name" value={draft.name} onChange={(name) => setDraft({ ...draft, name })} disabled={busy} />
            <label className="config-field settings-config-field">
              <span>Provider</span>
              <select value={draft.provider || 'openai_compatible'} onChange={(event) => setDraft({ ...draft, provider: event.target.value as LlmProviderProfileInput['provider'] })} disabled={busy}>
                {providerOptions.map((provider) => <option key={provider} value={provider}>{provider}</option>)}
              </select>
            </label>
            <TextField label="Base URL" value={draft.base_url} onChange={(base_url) => setDraft({ ...draft, base_url })} disabled={busy} />
            <TextField label="API key" value={draft.api_key} onChange={(api_key) => setDraft({ ...draft, api_key })} disabled={busy} secret hasSecret={Boolean(selectedProfile?.api_key_set)} />
            <NumberField label="Timeout" value={draft.timeout_seconds} onChange={(timeout_seconds) => setDraft({ ...draft, timeout_seconds })} disabled={busy} integer />
          </div>
          {result ? <p className={result.success ? 'settings-success-text' : 'settings-error-text'}>{result.message}</p> : null}
        </section>
      </div>
    </form>
  );
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
  const [draft, setDraft] = useState<LlmProfileInput>(() => (selectedProfile ? draftFromProfile(selectedProfile) : profileDefaults));
  const [keyTouched, setKeyTouched] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<SettingsErrorValue | null>(null);
  const [result, setResult] = useState<LlmTestResult | null>(null);

  useEffect(() => {
    setDraft(selectedProfile ? draftFromProfile(selectedProfile) : profileDefaults);
    setKeyTouched(false);
    setModels([]);
    setBusy(false);
    setError(null);
    setResult(null);
  }, [selectedProfile, selectedProfileId]);

  const baseDraft = selectedProfile ? draftFromProfile(selectedProfile) : profileDefaults;
  const dirty = stableConfigString(cleanProfileInput(draft)) !== stableConfigString(cleanProfileInput(baseDraft));

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
      if (testResult.models?.length) setModels(testResult.models);
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
      setModels(response.models.map((model) => model.id).filter(Boolean));
    } catch (caught) {
      setError(toSettingsError(caught, 'Failed to list profile models.'));
    } finally {
      setBusy(false);
    }
  }

  if (!selectedProfile && !isNew) {
    return <div className="settings-placeholder"><h2>Model Profile</h2><p>Select a model profile or create a new one.</p></div>;
  }

  return (
    <form className="settings-detail-form" onSubmit={(event) => event.preventDefault()}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">{profileInitials(String(draft.name || 'LLM'))}</div>
          <div>
            <h2>{String(draft.name || 'New model')}</h2>
            <p>
              <code>{String(draft.alias || 'profile_key')}</code>
              <span>{providerProfileLabel(String(draft.provider_profile_id || ''), providerProfiles)}</span>
            </p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {dirty ? (
            <button className="settings-primary-button" type="button" onClick={() => void saveProfile()} disabled={busy}>
              <Save size={14} />
              {busy ? 'Saving...' : 'Save'}
            </button>
          ) : null}
          {selectedProfile ? (
            <button className="settings-secondary-button" type="button" onClick={() => void duplicateProfile()} disabled={busy}>
              Duplicate
            </button>
          ) : null}
          {selectedProfile ? (
            <button className="settings-secondary-button danger" type="button" onClick={() => void deleteProfile()} disabled={busy}>
              <Trash2 size={14} />
              Delete
            </button>
          ) : null}
          <ToggleSwitch checked={Boolean(draft.enabled)} onChange={(enabled) => updateDraft({ enabled })} disabled={busy} />
        </div>
      </header>
      <div className="settings-detail-body">
        {error ? <SettingsApiError error={error} /> : null}
        <section className="detail-section">
          <div className="detail-section-heading">
            <h3>Model</h3>
            <div className="settings-button-row">
              {selectedProfile ? (
                <>
                  <button className="settings-secondary-button" type="button" onClick={() => void refreshProfileModels()} disabled={busy || !draft.provider_profile_id}>
                    <RefreshCw size={14} className={busy ? 'spin' : ''} />
                    Refresh models
                  </button>
                </>
              ) : null}
            </div>
          </div>
          <div className="settings-config-form llm-profile-form">
            <TextField label="Name" value={draft.name} onChange={(name) => updateDraft({ name })} disabled={busy} />
            <label className="config-field settings-config-field">
              <span>Provider profile</span>
              <select value={String(draft.provider_profile_id || '')} onChange={(event) => updateDraft({ provider_profile_id: event.target.value || null })} disabled={busy}>
                <option value="">Missing provider profile</option>
                {providerProfiles.map((provider) => (
                  <option key={provider.id} value={provider.id} disabled={!provider.enabled}>
                    {provider.name}{provider.enabled ? '' : ' - disabled'}
                  </option>
                ))}
              </select>
            </label>
            <label className="config-field settings-config-field">
              <span>Model ID</span>
              <input type="text" value={String(draft.model_id ?? '')} onChange={(event) => updateDraft({ model_id: event.target.value })} disabled={busy} />
              {models.length ? (
                <select value={String(draft.model_id ?? '')} onChange={(event) => updateDraft({ model_id: event.target.value })} disabled={busy}>
                  <option value="">Select refreshed model</option>
                  {models.map((model) => <option key={model} value={model}>{model}</option>)}
                </select>
              ) : null}
            </label>
            <TextField label="Notes" value={draft.notes} onChange={(notes) => updateDraft({ notes })} disabled={busy} textarea />
          </div>
          {result ? <p className={result.success ? 'settings-success-text' : 'settings-error-text'}>{result.message}</p> : null}
        </section>
        <section className="detail-section">
          <h3>Generation defaults</h3>
          <div className="settings-config-form llm-profile-form">
            <NumberField label="Temperature" value={draft.temperature} onChange={(temperature) => updateDraft({ temperature })} disabled={busy} />
            <NumberField label="Top P" value={draft.top_p} onChange={(top_p) => updateDraft({ top_p })} disabled={busy} />
            <NumberField label="Top K" value={draft.top_k} onChange={(top_k) => updateDraft({ top_k })} disabled={busy} integer />
            <NumberField label="Max tokens" value={draft.max_tokens} onChange={(max_tokens) => updateDraft({ max_tokens })} disabled={busy} integer />
          </div>
        </section>
        <section className="detail-section">
          <h3>Capabilities</h3>
          <p className="settings-muted-copy">
            Reasoning output declares expected output behavior only. It does not change provider request parameters.
          </p>
          <div className="llm-profile-flags">
            <ToggleSwitch checked={Boolean(draft.supports_vision)} onChange={(supports_vision) => updateDraft({ supports_vision })} label={<CapabilityToggleLabel kind="vision" label="Vision" />} disabled={busy} />
            <ToggleSwitch checked={Boolean(draft.supports_tools)} onChange={(supports_tools) => updateDraft({ supports_tools })} label={<CapabilityToggleLabel kind="tools" label="Tools" />} disabled={busy} />
            <ToggleSwitch checked={Boolean(draft.supports_reasoning)} onChange={(supports_reasoning) => updateDraft({ supports_reasoning })} label={<CapabilityToggleLabel kind="reasoning" label="Reasoning output" />} disabled={busy} />
            <ToggleSwitch checked={Boolean(draft.supports_streaming)} onChange={(supports_streaming) => updateDraft({ supports_streaming })} label={<CapabilityToggleLabel kind="streaming" label="Streaming" />} disabled={busy} />
          </div>
        </section>
        <section className="detail-section">
          <h3>Advanced</h3>
          <div className="settings-config-form llm-profile-form">
            <label className="config-field settings-config-field">
              <span>Profile key</span>
              <input
                type="text"
                value={String(draft.alias ?? '')}
                onChange={(event) => {
                  setKeyTouched(true);
                  updateDraft({ alias: sanitizeProfileKey(event.target.value) });
                }}
                disabled={busy}
              />
              <small>Used by agent manifests as llm.profile. This currently maps to API alias.</small>
            </label>
          </div>
        </section>
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
          {providerOptions.map((provider) => (
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
  const entries = Object.entries(input).filter(([key, value]) => {
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
