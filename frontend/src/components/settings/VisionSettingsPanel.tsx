import { FormEvent, useEffect, useMemo, useState } from 'react';
import { Eye, RefreshCw, Save, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../../api/client';
import type {
  InferenceModelInventoryItem,
  LlmProviderProfile,
  VisionArchitecture,
  VisionBackend,
  VisionModelProfile,
  VisionModelProfileInput,
  VisionTask,
} from '../../types';
import { LOCAL_TRANSFORMERS_PROVIDER } from '../../types';
import { stableConfigString } from './configUtils';
import { SettingsApiError, toSettingsError, type SettingsErrorValue } from './SettingsApiError';
import { SettingsApiExampleBlock, formatApiExampleJson, type SettingsApiExample } from './SettingsApiExampleBlock';
import { finalSafeRefSegment, sanitizeProfileKey, uniqueProfileKey } from './profileKeyUtils';
import { ToggleSwitch } from './ToggleSwitch';

const ARCHITECTURES: VisionArchitecture[] = ['florence2'];
const BACKENDS: VisionBackend[] = ['transformers'];
const VISION_TASKS: VisionTask[] = ['caption', 'detailed_caption', 'more_detailed_caption', 'ocr', 'object_detection'];
const VISION_REF_PREFIX = 'vision/';

const defaultVisionProfile: Partial<VisionModelProfile> = {
  name: '',
  alias: '',
  description: '',
  notes: '',
  enabled: true,
  external_inference_enabled: false,
  provider_profile_id: null,
  provider_model_id: '',
  architecture: 'florence2',
  backend: 'transformers',
  supported_tasks: ['caption', 'detailed_caption', 'more_detailed_caption', 'ocr', 'object_detection'],
  max_batch_size: null,
  metadata: {},
};

export function VisionSettingsPanel({
  profiles,
  providerProfiles,
  selectedProfileId,
  onProfilesChanged,
  onDirtyChange,
}: {
  profiles: VisionModelProfile[];
  providerProfiles: LlmProviderProfile[];
  selectedProfileId: string;
  onProfilesChanged: (selectedProfileId?: string) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation('settings');
  const selected = profiles.find((profile) => profile.id === selectedProfileId);
  const isNew = selectedProfileId === 'new';
  const initial = isNew ? defaultVisionProfile : selected;

  if (!initial) {
    return (
      <div className="settings-placeholder">
        <h2>{t('vision.empty.noProfileSelected')}</h2>
        <p>{profiles.length ? t('vision.empty.selectProfile') : t('vision.empty.noProfiles')}</p>
      </div>
    );
  }

  return (
    <VisionProfileForm
      initial={initial}
      profiles={profiles}
      providerProfiles={providerProfiles}
      isNew={isNew}
      onProfilesChanged={onProfilesChanged}
      onDirtyChange={onDirtyChange}
    />
  );
}

function VisionProfileForm({
  initial,
  profiles,
  providerProfiles,
  isNew,
  onProfilesChanged,
  onDirtyChange,
}: {
  initial: Partial<VisionModelProfile>;
  profiles: VisionModelProfile[];
  providerProfiles: LlmProviderProfile[];
  isNew: boolean;
  onProfilesChanged: (selectedProfileId?: string) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation(['settings', 'common', 'status', 'llm']);
  const [values, setValues] = useState<Partial<VisionModelProfile>>(initial);
  const [metadataText, setMetadataText] = useState(() => formatMetadata(initial.metadata));
  const [inventoryItems, setInventoryItems] = useState<InferenceModelInventoryItem[]>([]);
  const [inventoryWarnings, setInventoryWarnings] = useState<string[]>([]);
  const [inventoryRoot, setInventoryRoot] = useState('');
  const [busy, setBusy] = useState('');
  const [result, setResult] = useState('');
  const [error, setError] = useState<SettingsErrorValue | null>(null);
  const [profileKeyTouched, setProfileKeyTouched] = useState(false);
  const scopeId = isNew ? 'new-vision-model' : initial.id || '';
  const baselineKey = stableConfigString(buildVisionPayload(initial, initial.metadata || {}));
  const [draftReady, setDraftReady] = useState(() => ({ scopeId, baselineKey }));
  const hydrated = draftReady.scopeId === scopeId && draftReady.baselineKey === baselineKey;
  const parsedMetadata = useMemo(() => parseMetadata(metadataText), [metadataText]);
  const dirty = useMemo(() => {
    if (!hydrated) return false;
    if (!parsedMetadata.ok) return true;
    try {
      return stableConfigString(buildVisionPayload(values, parsedMetadata.value)) !== baselineKey;
    } catch {
      return true;
    }
  }, [baselineKey, hydrated, parsedMetadata, values]);

  const localProviderProfiles = providerProfiles.filter((profile) => profile.provider === LOCAL_TRANSFORMERS_PROVIDER);
  const selectedProvider = localProviderProfiles.find((profile) => profile.id === values.provider_profile_id);
  const selectedProviderMissing = Boolean(values.provider_profile_id && !selectedProvider);
  const inventoryOptions = inventoryItems.filter((item) => item.kind === 'vision' && isVisionRef(item.ref));
  const currentModelRef = String(values.provider_model_id || '');
  const currentRefMissing = Boolean(isVisionRef(currentModelRef) && !inventoryOptions.some((item) => item.ref === currentModelRef));
  const currentRefInvalid = Boolean(currentModelRef && !isVisionRef(currentModelRef));
  const metadataForFields = parsedMetadata.ok ? parsedMetadata.value : values.metadata || {};
  const trustRemoteCode = metadataForFields.trust_remote_code === true;
  const saveDisabled = Boolean(busy) || !selectedProvider;
  const supportedTasks = values.supported_tasks || [];
  const apiExampleModelId = values.alias ? `vision:${values.alias}` : 'vision:<profile_key>';
  const visionApiExamples: SettingsApiExample[] = [];
  if (supportedTasks.includes('caption')) {
    visionApiExamples.push({
      id: 'vision-caption',
      title: t('settings:apiExamples.vision.caption'),
      body: formatApiExampleJson({
        model: apiExampleModelId,
        task: 'caption',
        input: {
          type: 'image',
          image_base64: '...',
        },
      }),
    });
  }
  if (supportedTasks.includes('detailed_caption')) {
    visionApiExamples.push({
      id: 'vision-detailed-caption',
      title: t('settings:apiExamples.vision.detailedCaption'),
      body: formatApiExampleJson({
        model: apiExampleModelId,
        task: 'detailed_caption',
        input: {
          type: 'image',
          image_base64: '...',
        },
      }),
    });
  }
  if (supportedTasks.includes('more_detailed_caption')) {
    visionApiExamples.push({
      id: 'vision-more-detailed-caption',
      title: t('settings:apiExamples.vision.moreDetailedCaption'),
      body: formatApiExampleJson({
        model: apiExampleModelId,
        task: 'more_detailed_caption',
        input: {
          type: 'image',
          image_base64: '...',
        },
        options: {
          max_new_tokens: 512,
          num_beams: 3,
        },
      }),
    });
  }
  if (supportedTasks.includes('ocr')) {
    visionApiExamples.push({
      id: 'vision-ocr',
      title: t('settings:apiExamples.vision.ocr'),
      body: formatApiExampleJson({
        model: apiExampleModelId,
        task: 'ocr',
        input: {
          type: 'image',
          image_base64: '...',
        },
      }),
    });
  }
  if (supportedTasks.includes('object_detection')) {
    visionApiExamples.push({
      id: 'vision-object-detection',
      title: t('settings:apiExamples.vision.objectDetection'),
      body: formatApiExampleJson({
        model: apiExampleModelId,
        task: 'object_detection',
        input: {
          type: 'image',
          image_base64: '...',
        },
        options: {
          max_new_tokens: 1024,
          num_beams: 3,
        },
      }),
    });
  }

  useEffect(() => {
    setValues(initial);
    setMetadataText(formatMetadata(initial.metadata));
    setDraftReady({ scopeId, baselineKey });
  }, [baselineKey, initial, scopeId]);

  useEffect(() => {
    setBusy('');
    setResult('');
    setError(null);
    setInventoryWarnings([]);
    setProfileKeyTouched(false);
    void refreshInventory();
  }, [scopeId]);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  async function refreshInventory() {
    setBusy((current) => current || 'inventory');
    try {
      setError(null);
      const response = await api.listInferenceModelInventory('vision');
      setInventoryItems(response.items.filter((item) => item.kind === 'vision' && isVisionRef(item.ref)));
      setInventoryWarnings(response.warnings || []);
      setInventoryRoot(response.models_root || '');
      setResult(t('settings:vision.results.inventoryLoaded', { count: response.items.length }));
    } catch (caught) {
      setError(toSettingsError(caught, t('settings:vision.errors.inventoryLoadFailed')));
    } finally {
      setBusy((current) => (current === 'inventory' ? '' : current));
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy('saving');
    try {
      setError(null);
      if (!selectedProvider) {
        throw new Error(t('settings:vision.errors.localProviderRequired'));
      }
      if (!parsedMetadata.ok) {
        setError({ code: 'INVALID_METADATA_JSON', message: t('settings:vision.errors.invalidMetadataJson') });
        return;
      }
      const payload = buildVisionPayload(values, parsedMetadata.value);
      if (!payload.name?.trim()) {
        throw new Error(t('settings:vision.errors.nameRequired'));
      }
      if (!payload.alias?.trim()) {
        throw new Error(t('settings:vision.errors.profileKeyRequired'));
      }
      if (!payload.provider_model_id?.trim()) {
        throw new Error(t('settings:vision.errors.modelRefRequired'));
      }
      if (!isVisionRef(payload.provider_model_id)) {
        throw new Error(t('settings:vision.errors.modelRefSafeRefRequired'));
      }
      if (!payload.supported_tasks?.length) {
        throw new Error(t('settings:vision.errors.supportedTaskRequired'));
      }
      const saved = isNew
        ? await api.createVisionModel(payload)
        : await api.patchVisionModel(values.id || '', payload);
      await onProfilesChanged(saved.id);
      setResult(t('settings:vision.results.profileSaved'));
    } catch (caught) {
      setError(toSettingsError(caught, t('settings:vision.errors.saveFailed')));
    } finally {
      setBusy('');
    }
  }

  async function remove() {
    if (!values.id) return;
    if (!window.confirm(t('settings:vision.confirm.deleteProfile', { name: values.name || t('settings:objectList.untitledModel') }))) return;
    setBusy('deleting');
    try {
      setError(null);
      await api.deleteVisionModel(values.id);
      await onProfilesChanged();
      setResult(t('settings:vision.results.profileDeleted'));
    } catch (caught) {
      setError(toSettingsError(caught, t('settings:vision.errors.deleteFailed')));
    } finally {
      setBusy('');
    }
  }

  function patchValues(patch: Partial<VisionModelProfile>, options: { autoAlias?: boolean } = {}) {
    setValues((current) => {
      const next = { ...current, ...patch };
      if (isNew && !profileKeyTouched && options.autoAlias) {
        next.alias = uniqueProfileKey([next.name, finalSafeRefSegment(next.provider_model_id, VISION_REF_PREFIX)], profiles, next.id);
      }
      return next;
    });
  }

  function selectModelRef(ref: string) {
    const item = inventoryOptions.find((option) => option.ref === ref);
    patchValues({
      provider_model_id: ref,
      name: values.name?.trim() ? values.name : item?.name || values.name || '',
    }, { autoAlias: true });
  }

  function setTaskEnabled(task: VisionTask, enabled: boolean) {
    const current = new Set(values.supported_tasks || []);
    if (enabled) {
      current.add(task);
    } else {
      current.delete(task);
    }
    patchValues({ supported_tasks: VISION_TASKS.filter((item) => current.has(item)) });
  }

  function setTrustRemoteCode(enabled: boolean) {
    const source = parsedMetadata.ok ? parsedMetadata.value : values.metadata || {};
    const next = { ...source };
    if (enabled) {
      next.trust_remote_code = true;
    } else {
      delete next.trust_remote_code;
    }
    patchValues({ metadata: next });
    setMetadataText(formatMetadata(next));
  }

  return (
    <form className="settings-detail-form" onSubmit={save}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">{profileInitials(values.name || values.alias || currentModelRef || 'VM') || <Eye size={18} />}</div>
          <div>
            <h2>{values.name || t('settings:vision.titles.newProfile')}</h2>
            <p>
              <code>{`key:${values.alias || 'profile_key'}`}</code>
              <code>{`arch:${values.architecture || 'florence2'}`}</code>
              <span>{currentModelRef || t('settings:vision.empty.noModelRef')}</span>
            </p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {result ? <span className="settings-badge success">{result}</span> : null}
          {dirty ? (
            <button className="settings-primary-button" type="submit" disabled={saveDisabled}>
              <Save size={14} />
              {busy === 'saving' ? t('common:saving') : t('common:save')}
            </button>
          ) : null}
          {!isNew ? (
            <button className="settings-secondary-button danger" type="button" onClick={() => void remove()} disabled={Boolean(busy)}>
              <Trash2 size={14} />
              {t('common:delete')}
            </button>
          ) : null}
          <ToggleSwitch checked={values.enabled ?? true} onChange={(enabled) => patchValues({ enabled })} disabled={Boolean(busy)} />
        </div>
      </header>
      <div className="settings-detail-body">
        {error ? <SettingsApiError error={error} /> : null}
        <section className="detail-section">
          <div className="detail-section-heading">
            <h3>{t('settings:vision.sections.model')}</h3>
            <div className="settings-button-row">
              <button className="settings-secondary-button" type="button" onClick={() => void refreshInventory()} disabled={Boolean(busy)}>
                <RefreshCw size={14} className={busy === 'inventory' ? 'spin' : ''} />
                {busy === 'inventory' ? t('settings:vision.actions.refreshingInventory') : t('settings:vision.actions.refreshInventory')}
              </button>
            </div>
          </div>
          <div className="settings-config-form llm-profile-form">
            <TextField label={t('settings:vision.labels.name')} value={values.name || ''} onChange={(name) => patchValues({ name }, { autoAlias: true })} disabled={Boolean(busy)} />
            <label className="config-field settings-config-field">
              <span>{t('settings:vision.labels.providerProfile')}</span>
              <select
                value={values.provider_profile_id || ''}
                onChange={(event) => patchValues({ provider_profile_id: event.currentTarget.value || null })}
                disabled={Boolean(busy)}
              >
                <option value="">{t('settings:vision.empty.noLocalProviderSelected')}</option>
                {selectedProviderMissing ? <option value={values.provider_profile_id || ''}>{t('settings:vision.warnings.providerMissing')}</option> : null}
                {localProviderProfiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {profile.name} / {t(`llm:providers.${profile.provider}`)}
                    {profile.enabled ? '' : ` - ${t('status:common.disabled', { ns: 'status' })}`}
                  </option>
                ))}
              </select>
              <small>{t('settings:vision.help.localProviderOnly')}</small>
            </label>
            <label className="config-field settings-config-field">
              <span>{t('settings:vision.labels.modelRef')}</span>
              <select value={currentModelRef} onChange={(event) => selectModelRef(event.currentTarget.value)} disabled={Boolean(busy)}>
                <option value="">{inventoryOptions.length ? t('settings:vision.empty.selectInventoryRef') : t('settings:vision.empty.noInventoryRefs')}</option>
                {currentRefMissing ? <option value={currentModelRef}>{t('settings:vision.labels.missingCurrentRef', { ref: currentModelRef })}</option> : null}
                {inventoryOptions.map((item) => (
                  <option key={item.ref} value={item.ref} title={item.relative_path || item.ref}>
                    {item.name} ({item.ref})
                  </option>
                ))}
              </select>
              <small>{inventoryRoot ? t('settings:vision.help.inventoryRoot', { root: inventoryRoot }) : t('settings:vision.help.safeRef')}</small>
            </label>
            <label className="config-field settings-config-field boolean-field">
              <span>{t('settings:externalInference.enabled')}</span>
              <ToggleSwitch checked={values.external_inference_enabled ?? false} onChange={(external_inference_enabled) => patchValues({ external_inference_enabled })} disabled={Boolean(busy)} />
              <small>{t('settings:externalInference.help')}</small>
            </label>
          </div>
          {!selectedProvider && !selectedProviderMissing ? <p className="settings-warning-text">{t('settings:vision.warnings.localProviderRequired')}</p> : null}
          {selectedProviderMissing ? <p className="settings-warning-text">{t('settings:vision.warnings.providerMissing')}</p> : null}
          {selectedProvider && !selectedProvider.enabled ? <p className="settings-warning-text">{t('settings:vision.warnings.providerDisabled')}</p> : null}
          {currentRefMissing ? <p className="settings-warning-text">{t('settings:vision.warnings.modelRefMissing')}</p> : null}
          {currentRefInvalid ? <p className="settings-warning-text">{t('settings:vision.errors.modelRefSafeRefRequired')}</p> : null}
          {inventoryWarnings.map((warning) => <p key={warning} className="settings-warning-text">{warning}</p>)}
        </section>
        <section className="detail-section">
          <h3>{t('settings:vision.sections.profile')}</h3>
          <div className="settings-config-form llm-profile-form">
            <TextField label={t('settings:vision.labels.notes')} value={values.notes || ''} onChange={(notes) => patchValues({ notes })} disabled={Boolean(busy)} textarea />
          </div>
        </section>
        <section className="detail-section">
          <h3>{t('settings:vision.sections.runtime')}</h3>
          <div className="settings-config-form llm-profile-form">
            <SelectField label={t('settings:vision.labels.architecture')} value={values.architecture || 'florence2'} options={ARCHITECTURES} labelPrefix="settings:vision.architectures" onChange={() => undefined} disabled />
            <SelectField label={t('settings:vision.labels.backend')} value={values.backend || 'transformers'} options={BACKENDS} labelPrefix="settings:vision.backends" onChange={() => undefined} disabled />
            <NumberField label={t('settings:vision.labels.maxBatchSize')} value={values.max_batch_size ?? null} onChange={(max_batch_size) => patchValues({ max_batch_size })} disabled={Boolean(busy)} />
          </div>
        </section>
        <section className="detail-section">
          <h3>{t('settings:vision.sections.tasks')}</h3>
          <div className="llm-profile-flags">
            {VISION_TASKS.map((task) => (
              <ToggleSwitch
                key={task}
                checked={(values.supported_tasks || []).includes(task)}
                onChange={(checked) => setTaskEnabled(task, checked)}
                label={t(`settings:vision.tasks.${task}`)}
                disabled={Boolean(busy)}
              />
            ))}
          </div>
          {!(values.supported_tasks || []).length ? <p className="settings-warning-text">{t('settings:vision.errors.supportedTaskRequired')}</p> : null}
        </section>
        <section className="detail-section">
          <h3>{t('settings:vision.sections.advanced')}</h3>
          <div className="settings-config-form llm-profile-form">
            <TextField
              label={t('settings:vision.labels.profileKey')}
              value={values.alias || ''}
              onChange={(alias) => {
                setProfileKeyTouched(true);
                patchValues({ alias: sanitizeProfileKey(alias) });
              }}
              disabled={Boolean(busy)}
              help={t('settings:vision.help.profileKey')}
            />
          </div>
          <label className="config-field settings-config-field boolean-field">
            <span>{t('settings:vision.labels.trustRemoteCode')}</span>
            <ToggleSwitch checked={trustRemoteCode} onChange={setTrustRemoteCode} disabled={Boolean(busy)} />
            <small>{t('settings:vision.help.trustRemoteCode')}</small>
          </label>
          {trustRemoteCode ? <p className="settings-warning-text">{t('settings:vision.warnings.trustRemoteCode')}</p> : null}
          <label className="config-field settings-config-field">
            <span>{t('settings:vision.labels.metadataJson')}</span>
            <textarea rows={8} value={metadataText} onChange={(event) => setMetadataText(event.currentTarget.value)} disabled={Boolean(busy)} />
            <small>{t('settings:vision.help.metadataJson')}</small>
          </label>
          {!parsedMetadata.ok ? <p className="settings-warning-text">{t('settings:vision.errors.invalidMetadataJson')}</p> : null}
        </section>
        <SettingsApiExampleBlock
          endpoint="/api/inference/vision"
          modelId={apiExampleModelId}
          modelIdHelp={t('settings:apiExamples.modelIdHelp')}
          examples={visionApiExamples}
        />
      </div>
    </form>
  );
}

function TextField({
  label,
  value,
  onChange,
  disabled,
  textarea = false,
  help,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  textarea?: boolean;
  help?: string;
}) {
  return (
    <label className="config-field settings-config-field">
      <span>{label}</span>
      {textarea ? (
        <textarea value={value} onChange={(event) => onChange(event.currentTarget.value)} disabled={disabled} />
      ) : (
        <input type="text" value={value} onChange={(event) => onChange(event.currentTarget.value)} disabled={disabled} />
      )}
      {help ? <small>{help}</small> : null}
    </label>
  );
}

function NumberField({ label, value, onChange, disabled }: { label: string; value: number | null; onChange: (value: number | null) => void; disabled: boolean }) {
  return (
    <label className="config-field settings-config-field">
      <span>{label}</span>
      <input
        type="number"
        step={1}
        value={value === null || value === undefined ? '' : String(value)}
        onChange={(event) => {
          const raw = event.currentTarget.value;
          onChange(raw === '' ? null : Number(raw));
        }}
        disabled={disabled}
      />
    </label>
  );
}

function SelectField({
  label,
  value,
  options,
  labelPrefix,
  onChange,
  disabled,
}: {
  label: string;
  value: string;
  options: string[];
  labelPrefix: string;
  onChange: (value: string) => void;
  disabled: boolean;
}) {
  const { t } = useTranslation('settings');
  return (
    <label className="config-field settings-config-field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.currentTarget.value)} disabled={disabled}>
        {options.map((option) => (
          <option key={option} value={option}>
            {t(`${labelPrefix}.${option}`, { defaultValue: option })}
          </option>
        ))}
      </select>
    </label>
  );
}

function buildVisionPayload(values: Partial<VisionModelProfile>, metadata: Record<string, unknown>): VisionModelProfileInput {
  return {
    name: values.name ?? '',
    alias: values.alias ?? '',
    description: values.description ?? '',
    notes: values.notes ?? '',
    enabled: values.enabled ?? true,
    external_inference_enabled: values.external_inference_enabled ?? false,
    provider_profile_id: values.provider_profile_id || null,
    provider_model_id: values.provider_model_id ?? '',
    architecture: 'florence2',
    backend: 'transformers',
    supported_tasks: normalizeTasks(values.supported_tasks),
    max_batch_size: parseOptionalInteger(values.max_batch_size, 'Max batch size'),
    metadata,
  };
}

function normalizeTasks(tasks: VisionTask[] | undefined): VisionTask[] {
  const selected = new Set(tasks || []);
  return VISION_TASKS.filter((task) => selected.has(task));
}

function parseOptionalInteger(value: number | string | null | undefined, label: string): number | null {
  if (value === null || value === undefined || value === '') return null;
  const numberValue = typeof value === 'number' ? value : Number(value);
  if (!Number.isInteger(numberValue)) {
    throw new Error(`${label} must be a whole number.`);
  }
  return numberValue;
}

function parseMetadata(value: string): { ok: true; value: Record<string, unknown> } | { ok: false } {
  try {
    const parsed = value.trim() ? JSON.parse(value) : {};
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { ok: false };
    }
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch {
    return { ok: false };
  }
}

function formatMetadata(metadata: Record<string, unknown> | undefined): string {
  return JSON.stringify(metadata || {}, null, 2);
}

function isVisionRef(value: string): boolean {
  return value.startsWith(VISION_REF_PREFIX) && value.slice(VISION_REF_PREFIX.length).length > 0 && !value.slice(VISION_REF_PREFIX.length).includes('/') && !value.includes('\\');
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
