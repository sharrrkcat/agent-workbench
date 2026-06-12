import { FormEvent, useEffect, useMemo, useState } from 'react';
import { Image, RefreshCw, Save, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../../api/client';
import type {
  InferenceModelInventoryItem,
  LlmProviderProfile,
  MultimodalEmbeddingArchitecture,
  MultimodalEmbeddingBackend,
  MultimodalEmbeddingInputType,
  MultimodalEmbeddingModelProfile,
  MultimodalEmbeddingModelProfileInput,
  MultimodalEmbeddingPoolingStrategy,
} from '../../types';
import { LOCAL_TRANSFORMERS_PROVIDER } from '../../types';
import { stableConfigString } from './configUtils';
import { SettingsApiError, toSettingsError, type SettingsErrorValue } from './SettingsApiError';
import { SettingsApiExampleBlock, formatApiExampleJson, type SettingsApiExample } from './SettingsApiExampleBlock';
import { ToggleSwitch } from './ToggleSwitch';

const ARCHITECTURES: MultimodalEmbeddingArchitecture[] = ['clip', 'open_clip', 'siglip2', 'dinov2'];
const BACKENDS: MultimodalEmbeddingBackend[] = ['auto', 'transformers', 'open_clip'];
const POOLING_STRATEGIES: MultimodalEmbeddingPoolingStrategy[] = ['model_default', 'cls', 'mean', 'pooler'];
const IMAGE_EMBEDDING_REF_PREFIX = 'image_embedding/';

const defaultMultimodalEmbeddingProfile: Partial<MultimodalEmbeddingModelProfile> = {
  name: '',
  description: '',
  notes: '',
  enabled: true,
  external_inference_enabled: false,
  provider_profile_id: null,
  provider_model_id: '',
  architecture: 'clip',
  backend: 'auto',
  embedding_space: null,
  dimensions: null,
  normalize_default: true,
  supported_input_types: ['image', 'text'],
  preprocessing_signature: null,
  pooling_strategy: 'model_default',
  max_batch_size: null,
  metadata: {},
};

export function MultimodalEmbeddingSettingsPanel({
  profiles,
  providerProfiles,
  selectedProfileId,
  onProfilesChanged,
  onDirtyChange,
}: {
  profiles: MultimodalEmbeddingModelProfile[];
  providerProfiles: LlmProviderProfile[];
  selectedProfileId: string;
  onProfilesChanged: (selectedProfileId?: string) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation('settings');
  const selected = profiles.find((profile) => profile.id === selectedProfileId);
  const isNew = selectedProfileId === 'new';
  const initial = isNew ? defaultMultimodalEmbeddingProfile : selected;

  if (!initial) {
    return (
      <div className="settings-placeholder">
        <h2>{t('multimodal.empty.noProfileSelected')}</h2>
        <p>{profiles.length ? t('multimodal.empty.selectProfile') : t('multimodal.empty.noProfiles')}</p>
      </div>
    );
  }

  return (
    <MultimodalEmbeddingProfileForm
      initial={initial}
      profiles={profiles}
      providerProfiles={providerProfiles}
      isNew={isNew}
      onProfilesChanged={onProfilesChanged}
      onDirtyChange={onDirtyChange}
    />
  );
}

function MultimodalEmbeddingProfileForm({
  initial,
  profiles,
  providerProfiles,
  isNew,
  onProfilesChanged,
  onDirtyChange,
}: {
  initial: Partial<MultimodalEmbeddingModelProfile>;
  profiles: MultimodalEmbeddingModelProfile[];
  providerProfiles: LlmProviderProfile[];
  isNew: boolean;
  onProfilesChanged: (selectedProfileId?: string) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation(['settings', 'common', 'status', 'llm']);
  const [values, setValues] = useState<Partial<MultimodalEmbeddingModelProfile>>(initial);
  const [metadataText, setMetadataText] = useState(() => formatMetadata(initial.metadata));
  const [inventoryItems, setInventoryItems] = useState<InferenceModelInventoryItem[]>([]);
  const [inventoryWarnings, setInventoryWarnings] = useState<string[]>([]);
  const [inventoryRoot, setInventoryRoot] = useState('');
  const [busy, setBusy] = useState('');
  const [result, setResult] = useState('');
  const [error, setError] = useState<SettingsErrorValue | null>(null);
  const scopeId = isNew ? 'new-multimodal-embedding' : initial.id || '';
  const baselineKey = stableConfigString(buildMultimodalEmbeddingPayload(initial, initial.metadata || {}));
  const [draftReady, setDraftReady] = useState(() => ({ scopeId, baselineKey }));
  const hydrated = draftReady.scopeId === scopeId && draftReady.baselineKey === baselineKey;
  const parsedMetadata = useMemo(() => parseMetadata(metadataText), [metadataText]);
  const dirty = useMemo(() => {
    if (!hydrated) return false;
    if (!parsedMetadata.ok) return true;
    try {
      return stableConfigString(buildMultimodalEmbeddingPayload(values, parsedMetadata.value)) !== baselineKey;
    } catch {
      return true;
    }
  }, [baselineKey, hydrated, parsedMetadata, values]);

  const localProviderProfiles = providerProfiles.filter((profile) => profile.provider === LOCAL_TRANSFORMERS_PROVIDER);
  const selectedProvider = localProviderProfiles.find((profile) => profile.id === values.provider_profile_id);
  const selectedProviderMissing = Boolean(values.provider_profile_id && !selectedProvider);
  const inventoryOptions = inventoryItems.filter((item) => item.kind === 'image_embedding' && isImageEmbeddingRef(item.ref));
  const currentModelRef = String(values.provider_model_id || '');
  const currentRefMissing = Boolean(isImageEmbeddingRef(currentModelRef) && !inventoryOptions.some((item) => item.ref === currentModelRef));
  const architecture = values.architecture || 'clip';
  const supportsText = architecture !== 'dinov2' && (values.supported_input_types || []).includes('text');
  const metadataForFields = parsedMetadata.ok ? parsedMetadata.value : values.metadata || {};
  const openClipModelName = stringMetadataValue(metadataForFields.open_clip_model_name);
  const openClipCheckpoint = stringMetadataValue(metadataForFields.open_clip_checkpoint);
  const saveDisabled = Boolean(busy) || !selectedProvider;
  const apiExampleModelId = values.id ? `multimodal:${values.id}` : 'multimodal:<profile_id>';
  const multimodalApiExamples: SettingsApiExample[] = [
    {
      id: 'multimodal-image',
      title: t('settings:apiExamples.multimodal.image'),
      body: formatApiExampleJson({
        model: apiExampleModelId,
        inputs: [
          {
            type: 'image_base64',
            data: '...',
          },
        ],
        normalize: values.normalize_default ?? true,
      }),
    },
  ];
  if (supportsText) {
    multimodalApiExamples.push(
      {
        id: 'multimodal-text',
        title: t('settings:apiExamples.multimodal.text'),
        body: formatApiExampleJson({
          model: apiExampleModelId,
          inputs: [
            {
              type: 'text',
              text: 'red robot',
            },
          ],
          normalize: values.normalize_default ?? true,
        }),
      },
      {
        id: 'multimodal-image-text',
        title: t('settings:apiExamples.multimodal.imageText'),
        body: formatApiExampleJson({
          model: apiExampleModelId,
          inputs: [
            {
              type: 'image_base64',
              data: '...',
            },
            {
              type: 'text',
              text: 'red robot',
            },
          ],
          normalize: values.normalize_default ?? true,
        }),
      },
    );
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
    void refreshInventory();
  }, [scopeId]);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  async function refreshInventory() {
    setBusy((current) => current || 'inventory');
    try {
      setError(null);
      const response = await api.listInferenceModelInventory('image_embedding');
      setInventoryItems(response.items.filter((item) => item.kind === 'image_embedding' && isImageEmbeddingRef(item.ref)));
      setInventoryWarnings(response.warnings || []);
      setInventoryRoot(response.models_root || '');
      setResult(t('settings:multimodal.results.inventoryLoaded', { count: response.items.length }));
    } catch (caught) {
      setError(toSettingsError(caught, t('settings:multimodal.errors.inventoryLoadFailed')));
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
        throw new Error(t('settings:multimodal.errors.localProviderRequired'));
      }
      if (!parsedMetadata.ok) {
        setError({ code: 'INVALID_METADATA_JSON', message: t('settings:multimodal.errors.invalidMetadataJson') });
        return;
      }
      if ((values.architecture || 'clip') === 'open_clip' && !stringMetadataValue(parsedMetadata.value.open_clip_model_name).trim()) {
        setError({ code: 'OPEN_CLIP_MODEL_NAME_REQUIRED', message: t('settings:multimodal.errors.openClipModelNameRequired') });
        return;
      }
      const payload = buildMultimodalEmbeddingPayload(values, parsedMetadata.value);
      if (!payload.name?.trim()) {
        throw new Error(t('settings:multimodal.errors.nameRequired'));
      }
      if (!payload.provider_model_id?.trim()) {
        throw new Error(t('settings:multimodal.errors.modelRefRequired'));
      }
      if (!isImageEmbeddingRef(payload.provider_model_id)) {
        throw new Error(t('settings:multimodal.errors.modelRefSafeRefRequired'));
      }
      const saved = isNew
        ? await api.createMultimodalEmbeddingModel(payload)
        : await api.patchMultimodalEmbeddingModel(values.id || '', payload);
      await onProfilesChanged(saved.id);
      setResult(t('settings:multimodal.results.profileSaved'));
    } catch (caught) {
      setError(toSettingsError(caught, t('settings:multimodal.errors.saveFailed')));
    } finally {
      setBusy('');
    }
  }

  async function remove() {
    if (!values.id) return;
    if (!window.confirm(t('settings:multimodal.confirm.deleteProfile', { name: values.name || t('settings:objectList.untitledModel') }))) return;
    setBusy('deleting');
    try {
      setError(null);
      await api.deleteMultimodalEmbeddingModel(values.id);
      await onProfilesChanged();
      setResult(t('settings:multimodal.results.profileDeleted'));
    } catch (caught) {
      setError(toSettingsError(caught, t('settings:multimodal.errors.deleteFailed')));
    } finally {
      setBusy('');
    }
  }

  function patchValues(patch: Partial<MultimodalEmbeddingModelProfile>) {
    setValues((current) => ({ ...current, ...patch }));
  }

  function setArchitecture(architecture: MultimodalEmbeddingArchitecture) {
    patchValues({
      architecture,
      supported_input_types: normalizeSupportedInputTypes(architecture, values.supported_input_types),
    });
  }

  function setTextSupported(enabled: boolean) {
    if ((values.architecture || 'clip') === 'dinov2') return;
    patchValues({ supported_input_types: enabled ? ['image', 'text'] : ['image'] });
  }

  function selectModelRef(ref: string) {
    const item = inventoryOptions.find((option) => option.ref === ref);
    patchValues({
      provider_model_id: ref,
      name: values.name?.trim() ? values.name : item?.name || values.name || '',
    });
  }

  function updateMetadataField(key: 'open_clip_model_name' | 'open_clip_checkpoint', value: string) {
    const source = parsedMetadata.ok ? parsedMetadata.value : values.metadata || {};
    const next = { ...source };
    const trimmed = value.trim();
    if (trimmed) {
      next[key] = trimmed;
    } else {
      delete next[key];
    }
    patchValues({ metadata: next });
    setMetadataText(formatMetadata(next));
  }

  return (
    <form className="settings-detail-form" onSubmit={save}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">{profileInitials(values.name || currentModelRef || 'ME') || <Image size={18} />}</div>
          <div>
            <h2>{values.name || t('settings:multimodal.titles.newProfile')}</h2>
            <p>
              <code>{`arch:${values.architecture || 'clip'}`}</code>
              <span>{currentModelRef || t('settings:multimodal.empty.noModelRef')}</span>
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
            <h3>{t('settings:multimodal.sections.model')}</h3>
            <div className="settings-button-row">
              <button className="settings-secondary-button" type="button" onClick={() => void refreshInventory()} disabled={Boolean(busy)}>
                <RefreshCw size={14} className={busy === 'inventory' ? 'spin' : ''} />
                {busy === 'inventory' ? t('settings:multimodal.actions.refreshingInventory') : t('settings:multimodal.actions.refreshInventory')}
              </button>
            </div>
          </div>
          <div className="settings-config-form llm-profile-form">
            <TextField label={t('settings:multimodal.labels.name')} value={values.name || ''} onChange={(name) => patchValues({ name })} disabled={Boolean(busy)} />
            <label className="config-field settings-config-field">
              <span>{t('settings:multimodal.labels.providerProfile')}</span>
              <select
                value={values.provider_profile_id || ''}
                onChange={(event) => patchValues({ provider_profile_id: event.currentTarget.value || null })}
                disabled={Boolean(busy)}
              >
                <option value="">{t('settings:multimodal.empty.noLocalProviderSelected')}</option>
                {selectedProviderMissing ? <option value={values.provider_profile_id || ''}>{t('settings:multimodal.warnings.providerMissing')}</option> : null}
                {localProviderProfiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {profile.name} / {t(`llm:providers.${profile.provider}`)}
                    {profile.enabled ? '' : ` - ${t('status:common.disabled', { ns: 'status' })}`}
                  </option>
                ))}
              </select>
              <small>{t('settings:multimodal.help.localProviderOnly')}</small>
            </label>
            <label className="config-field settings-config-field">
              <span>{t('settings:multimodal.labels.modelRef')}</span>
              <select value={currentModelRef} onChange={(event) => selectModelRef(event.currentTarget.value)} disabled={Boolean(busy)}>
                <option value="">{inventoryOptions.length ? t('settings:multimodal.empty.selectInventoryRef') : t('settings:multimodal.empty.noInventoryRefs')}</option>
                {currentRefMissing ? <option value={currentModelRef}>{t('settings:multimodal.labels.missingCurrentRef', { ref: currentModelRef })}</option> : null}
                {inventoryOptions.map((item) => (
                  <option key={item.ref} value={item.ref} title={item.relative_path || item.ref}>
                    {item.name} ({item.ref})
                  </option>
                ))}
              </select>
              <small>{inventoryRoot ? t('settings:multimodal.help.inventoryRoot', { root: inventoryRoot }) : t('settings:multimodal.help.safeRef')}</small>
            </label>
            <label className="config-field settings-config-field boolean-field">
              <span>{t('settings:externalInference.enabled')}</span>
              <ToggleSwitch checked={values.external_inference_enabled ?? false} onChange={(external_inference_enabled) => patchValues({ external_inference_enabled })} disabled={Boolean(busy)} />
              <small>{t('settings:externalInference.help')}</small>
            </label>
          </div>
          {!selectedProvider && !selectedProviderMissing ? <p className="settings-warning-text">{t('settings:multimodal.warnings.localProviderRequired')}</p> : null}
          {selectedProviderMissing ? <p className="settings-warning-text">{t('settings:multimodal.warnings.providerMissing')}</p> : null}
          {selectedProvider && !selectedProvider.enabled ? <p className="settings-warning-text">{t('settings:multimodal.warnings.providerDisabled')}</p> : null}
          {currentRefMissing ? <p className="settings-warning-text">{t('settings:multimodal.warnings.modelRefMissing')}</p> : null}
          {inventoryWarnings.map((warning) => <p key={warning} className="settings-warning-text">{warning}</p>)}
        </section>
        <section className="detail-section">
          <h3>{t('settings:multimodal.sections.profile')}</h3>
          <div className="settings-config-form llm-profile-form">
            <TextField label={t('settings:multimodal.labels.description')} value={values.description || ''} onChange={(description) => patchValues({ description })} disabled={Boolean(busy)} textarea />
            <TextField label={t('settings:multimodal.labels.notes')} value={values.notes || ''} onChange={(notes) => patchValues({ notes })} disabled={Boolean(busy)} textarea />
          </div>
        </section>
        <section className="detail-section">
          <h3>{t('settings:multimodal.sections.architecture')}</h3>
          <div className="settings-config-form llm-profile-form">
            <SelectField label={t('settings:multimodal.labels.architecture')} value={architecture} options={ARCHITECTURES} labelPrefix="settings:multimodal.architectures" onChange={(value) => setArchitecture(value as MultimodalEmbeddingArchitecture)} disabled={Boolean(busy)} />
            <SelectField label={t('settings:multimodal.labels.backend')} value={values.backend || 'auto'} options={BACKENDS} labelPrefix="settings:multimodal.backends" onChange={(value) => patchValues({ backend: value as MultimodalEmbeddingBackend })} disabled={Boolean(busy)} />
          </div>
          <div className="llm-profile-flags">
            <ToggleSwitch checked onChange={() => undefined} label={t('settings:multimodal.labels.imageInput')} disabled />
            <ToggleSwitch checked={supportsText} onChange={setTextSupported} label={t('settings:multimodal.labels.textInput')} disabled={Boolean(busy) || architecture === 'dinov2'} />
          </div>
          {architecture === 'dinov2' ? <p className="settings-muted-copy">{t('settings:multimodal.help.dinov2ImageOnly')}</p> : null}
        </section>
        <section className="detail-section">
          <h3>{t('settings:multimodal.sections.embedding')}</h3>
          <div className="settings-config-form llm-profile-form">
            <NumberField label={t('settings:multimodal.labels.dimensions')} value={values.dimensions ?? null} onChange={(dimensions) => patchValues({ dimensions })} disabled={Boolean(busy)} />
            <TextField label={t('settings:multimodal.labels.embeddingSpace')} value={values.embedding_space || ''} onChange={(embedding_space) => patchValues({ embedding_space })} disabled={Boolean(busy)} />
            <TextField label={t('settings:multimodal.labels.preprocessingSignature')} value={values.preprocessing_signature || ''} onChange={(preprocessing_signature) => patchValues({ preprocessing_signature })} disabled={Boolean(busy)} />
            <SelectField label={t('settings:multimodal.labels.poolingStrategy')} value={values.pooling_strategy || 'model_default'} options={POOLING_STRATEGIES} labelPrefix="settings:multimodal.pooling" onChange={(pooling_strategy) => patchValues({ pooling_strategy: pooling_strategy as MultimodalEmbeddingPoolingStrategy })} disabled={Boolean(busy)} />
            <NumberField label={t('settings:multimodal.labels.maxBatchSize')} value={values.max_batch_size ?? null} onChange={(max_batch_size) => patchValues({ max_batch_size })} disabled={Boolean(busy)} />
            <label className="config-field settings-config-field boolean-field">
              <span>{t('settings:multimodal.labels.normalizeDefault')}</span>
              <ToggleSwitch checked={values.normalize_default ?? true} onChange={(normalize_default) => patchValues({ normalize_default })} disabled={Boolean(busy)} />
            </label>
          </div>
        </section>
        <section className="detail-section">
          <h3>{t('settings:multimodal.sections.advanced')}</h3>
          {architecture === 'open_clip' ? (
            <div className="settings-config-form llm-profile-form">
              <TextField label={t('settings:multimodal.labels.openClipModelName')} value={openClipModelName} onChange={(value) => updateMetadataField('open_clip_model_name', value)} disabled={Boolean(busy)} />
              <TextField label={t('settings:multimodal.labels.openClipCheckpoint')} value={openClipCheckpoint} onChange={(value) => updateMetadataField('open_clip_checkpoint', value)} disabled={Boolean(busy)} />
            </div>
          ) : null}
          <label className="config-field settings-config-field">
            <span>{t('settings:multimodal.labels.metadataJson')}</span>
            <textarea rows={8} value={metadataText} onChange={(event) => setMetadataText(event.currentTarget.value)} disabled={Boolean(busy)} />
            <small>{t('settings:multimodal.help.metadataJson')}</small>
          </label>
          {!parsedMetadata.ok ? <p className="settings-warning-text">{t('settings:multimodal.errors.invalidMetadataJson')}</p> : null}
        </section>
        <SettingsApiExampleBlock
          endpoint="/api/inference/embeddings/multimodal"
          modelId={apiExampleModelId}
          examples={multimodalApiExamples}
          note={architecture === 'dinov2' ? t('settings:apiExamples.multimodal.dinov2ImageOnly') : undefined}
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
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  textarea?: boolean;
}) {
  return (
    <label className="config-field settings-config-field">
      <span>{label}</span>
      {textarea ? (
        <textarea value={value} onChange={(event) => onChange(event.currentTarget.value)} disabled={disabled} />
      ) : (
        <input type="text" value={value} onChange={(event) => onChange(event.currentTarget.value)} disabled={disabled} />
      )}
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

function buildMultimodalEmbeddingPayload(values: Partial<MultimodalEmbeddingModelProfile>, metadata: Record<string, unknown>): MultimodalEmbeddingModelProfileInput {
  const architecture = values.architecture || 'clip';
  return {
    name: values.name ?? '',
    description: values.description ?? '',
    notes: values.notes ?? '',
    enabled: values.enabled ?? true,
    external_inference_enabled: values.external_inference_enabled ?? false,
    provider_profile_id: values.provider_profile_id || null,
    provider_model_id: values.provider_model_id ?? '',
    architecture,
    backend: values.backend || 'auto',
    embedding_space: optionalString(values.embedding_space),
    dimensions: parseOptionalInteger(values.dimensions, 'Dimensions'),
    normalize_default: values.normalize_default ?? true,
    supported_input_types: normalizeSupportedInputTypes(architecture, values.supported_input_types),
    preprocessing_signature: optionalString(values.preprocessing_signature),
    pooling_strategy: values.pooling_strategy || 'model_default',
    max_batch_size: parseOptionalInteger(values.max_batch_size, 'Max batch size'),
    metadata,
  };
}

function normalizeSupportedInputTypes(architecture: MultimodalEmbeddingArchitecture, inputTypes: MultimodalEmbeddingInputType[] | undefined): MultimodalEmbeddingInputType[] {
  if (architecture === 'dinov2') return ['image'];
  return inputTypes?.includes('text') ? ['image', 'text'] : ['image'];
}

function parseOptionalInteger(value: number | string | null | undefined, label: string): number | null {
  if (value === null || value === undefined || value === '') return null;
  const numberValue = typeof value === 'number' ? value : Number(value);
  if (!Number.isInteger(numberValue)) {
    throw new Error(`${label} must be a whole number.`);
  }
  return numberValue;
}

function optionalString(value: string | null | undefined): string | null {
  const trimmed = String(value || '').trim();
  return trimmed ? trimmed : null;
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

function stringMetadataValue(value: unknown): string {
  return typeof value === 'string' ? value : value === undefined || value === null ? '' : String(value);
}

function isImageEmbeddingRef(value: string): boolean {
  return value.startsWith(IMAGE_EMBEDDING_REF_PREFIX) && value.slice(IMAGE_EMBEDDING_REF_PREFIX.length).length > 0 && !value.slice(IMAGE_EMBEDDING_REF_PREFIX.length).includes('/') && !value.includes('\\');
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
