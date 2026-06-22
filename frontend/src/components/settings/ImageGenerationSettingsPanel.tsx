import { FormEvent, useEffect, useMemo, useState } from 'react';
import { Image, Power, RefreshCw, Save, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { api } from '../../api/client';
import type {
  ImageGenerationArchitecture,
  ImageGenerationDevice,
  ImageGenerationDtype,
  ImageGenerationModelInventoryItem,
  ImageGenerationModelProfile,
  ImageGenerationModelProfileInput,
  ImageGenerationRuntimeStatus,
  ImageGenerationUnloadResult,
  ImageGenerationVariant,
} from '../../types';
import { stableConfigString } from './configUtils';
import { SettingsApiError, toSettingsError, type SettingsErrorValue } from './SettingsApiError';
import { finalSafeRefSegment, sanitizeProfileKey, uniqueProfileKey } from './profileKeyUtils';
import { ToggleSwitch } from './ToggleSwitch';

const ARCHITECTURES: ImageGenerationArchitecture[] = ['sd15', 'sdxl', 'z_image'];
const VARIANTS: ImageGenerationVariant[] = ['base', 'pony', 'illustrious', 'noobai', 'custom'];
const SDXL_ONLY_VARIANTS: ImageGenerationVariant[] = ['pony', 'illustrious', 'noobai'];
const DTYPES: ImageGenerationDtype[] = ['auto', 'fp16', 'bf16', 'fp32'];
const DEVICES: ImageGenerationDevice[] = ['auto', 'cuda', 'cpu'];
const CHECKPOINT_REF_PREFIX = 'image_generation/checkpoints/';
const VAE_REF_PREFIX = 'image_generation/vae/';

const defaultImageGenerationProfile: Partial<ImageGenerationModelProfile> = {
  name: '',
  alias: '',
  description: '',
  notes: '',
  enabled: true,
  architecture: 'sdxl',
  variant: 'base',
  checkpoint_ref: '',
  vae_ref: null,
  dtype: 'auto',
  device: 'auto',
  clip_skip: null,
  supported_tasks: ['txt2img'],
  metadata: {},
};

export function ImageGenerationSettingsPanel({
  profiles,
  selectedProfileId,
  onProfilesChanged,
  onDirtyChange,
}: {
  profiles: ImageGenerationModelProfile[];
  selectedProfileId: string;
  onProfilesChanged: (selectedProfileId?: string) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation('settings');
  const selected = profiles.find((profile) => profile.id === selectedProfileId);
  const isNew = selectedProfileId === 'new';
  const initial = isNew ? defaultImageGenerationProfile : selected;

  if (!initial) {
    return (
      <div className="settings-placeholder">
        <h2>{t('imageGeneration.empty.noProfileSelected')}</h2>
        <p>{profiles.length ? t('imageGeneration.empty.selectProfile') : t('imageGeneration.empty.noProfiles')}</p>
      </div>
    );
  }

  return (
    <ImageGenerationProfileForm
      initial={initial}
      profiles={profiles}
      isNew={isNew}
      onProfilesChanged={onProfilesChanged}
      onDirtyChange={onDirtyChange}
    />
  );
}

function ImageGenerationProfileForm({
  initial,
  profiles,
  isNew,
  onProfilesChanged,
  onDirtyChange,
}: {
  initial: Partial<ImageGenerationModelProfile>;
  profiles: ImageGenerationModelProfile[];
  isNew: boolean;
  onProfilesChanged: (selectedProfileId?: string) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation(['settings', 'common', 'status']);
  const [values, setValues] = useState<Partial<ImageGenerationModelProfile>>(initial);
  const [metadataText, setMetadataText] = useState(() => formatMetadata(initial.metadata));
  const [checkpointItems, setCheckpointItems] = useState<ImageGenerationModelInventoryItem[]>([]);
  const [vaeItems, setVaeItems] = useState<ImageGenerationModelInventoryItem[]>([]);
  const [inventoryWarnings, setInventoryWarnings] = useState<string[]>([]);
  const [inventoryRoot, setInventoryRoot] = useState('');
  const [runtimeStatus, setRuntimeStatus] = useState<ImageGenerationRuntimeStatus | null>(null);
  const [unloadResult, setUnloadResult] = useState<ImageGenerationUnloadResult | null>(null);
  const [busy, setBusy] = useState('');
  const [result, setResult] = useState('');
  const [error, setError] = useState<SettingsErrorValue | null>(null);
  const [profileKeyTouched, setProfileKeyTouched] = useState(false);
  const scopeId = isNew ? 'new-image-generation-model' : initial.id || '';
  const baselineKey = stableConfigString(buildImageGenerationPayload(initial, initial.metadata || {}));
  const [draftReady, setDraftReady] = useState(() => ({ scopeId, baselineKey }));
  const hydrated = draftReady.scopeId === scopeId && draftReady.baselineKey === baselineKey;
  const parsedMetadata = useMemo(() => parseMetadata(metadataText), [metadataText]);
  const dirty = useMemo(() => {
    if (!hydrated) return false;
    if (!parsedMetadata.ok) return true;
    try {
      return stableConfigString(buildImageGenerationPayload(values, parsedMetadata.value)) !== baselineKey;
    } catch {
      return true;
    }
  }, [baselineKey, hydrated, parsedMetadata, values]);

  const currentCheckpointRef = String(values.checkpoint_ref || '');
  const currentVaeRef = String(values.vae_ref || '');
  const checkpointOptions = checkpointItems.filter((item) => item.kind === 'checkpoint' && isCheckpointRef(item.ref));
  const vaeOptions = vaeItems.filter((item) => item.kind === 'vae' && isVaeRef(item.ref));
  const checkpointRefMissing = Boolean(isCheckpointRef(currentCheckpointRef) && !checkpointOptions.some((item) => item.ref === currentCheckpointRef));
  const checkpointRefInvalid = Boolean(currentCheckpointRef && !isCheckpointRef(currentCheckpointRef));
  const vaeRefMissing = Boolean(isVaeRef(currentVaeRef) && !vaeOptions.some((item) => item.ref === currentVaeRef));
  const vaeRefInvalid = Boolean(currentVaeRef && !isVaeRef(currentVaeRef));
  const currentArchitecture = (values.architecture || 'sdxl') as ImageGenerationArchitecture;
  const currentVariant = (values.variant || 'base') as ImageGenerationVariant;
  const saveDisabled = Boolean(busy);

  useEffect(() => {
    setValues(initial);
    setMetadataText(formatMetadata(initial.metadata));
    setDraftReady({ scopeId, baselineKey });
  }, [baselineKey, initial, scopeId]);

  useEffect(() => {
    setBusy('');
    setResult('');
    setError(null);
    setUnloadResult(null);
    setInventoryWarnings([]);
    setProfileKeyTouched(false);
    void refreshInventory();
    void refreshStatus();
  }, [scopeId]);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  async function refreshInventory() {
    setBusy((current) => current || 'inventory');
    try {
      setError(null);
      const [checkpoints, vaes] = await Promise.all([
        api.listImageGenerationModelInventory('checkpoint'),
        api.listImageGenerationModelInventory('vae'),
      ]);
      setCheckpointItems(checkpoints.items.filter((item) => item.kind === 'checkpoint' && isCheckpointRef(item.ref)));
      setVaeItems(vaes.items.filter((item) => item.kind === 'vae' && isVaeRef(item.ref)));
      setInventoryWarnings([...(checkpoints.warnings || []), ...(vaes.warnings || [])]);
      setInventoryRoot(checkpoints.models_root || vaes.models_root || '');
      setResult(t('settings:imageGeneration.results.inventoryLoaded', { count: checkpoints.items.length + vaes.items.length }));
    } catch (caught) {
      setError(toSettingsError(caught, t('settings:imageGeneration.errors.inventoryLoadFailed')));
    } finally {
      setBusy((current) => (current === 'inventory' ? '' : current));
    }
  }

  async function refreshStatus() {
    setBusy((current) => current || 'status');
    try {
      setError(null);
      setRuntimeStatus(await api.getImageGenerationStatus());
    } catch (caught) {
      setError(toSettingsError(caught, t('settings:imageGeneration.errors.statusLoadFailed')));
    } finally {
      setBusy((current) => (current === 'status' ? '' : current));
    }
  }

  async function unloadCache(profileScoped: boolean) {
    setBusy('unload');
    try {
      setError(null);
      const response = await api.unloadImageGeneration(profileScoped ? values.id || values.alias || '' : null);
      setUnloadResult(response);
      await refreshStatus();
    } catch (caught) {
      setError(toSettingsError(caught, t('settings:imageGeneration.errors.unloadFailed')));
    } finally {
      setBusy('');
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy('saving');
    try {
      setError(null);
      if (!parsedMetadata.ok) {
        setError({ code: 'INVALID_METADATA_JSON', message: t('settings:imageGeneration.errors.invalidMetadataJson') });
        return;
      }
      const payload = buildImageGenerationPayload(values, parsedMetadata.value);
      if (!payload.name?.trim()) {
        throw new Error(t('settings:imageGeneration.errors.nameRequired'));
      }
      if (!payload.alias?.trim()) {
        throw new Error(t('settings:imageGeneration.errors.profileKeyRequired'));
      }
      if (!payload.checkpoint_ref?.trim()) {
        throw new Error(t('settings:imageGeneration.errors.checkpointRefRequired'));
      }
      if (!isCheckpointRef(payload.checkpoint_ref)) {
        throw new Error(t('settings:imageGeneration.errors.checkpointRefSafeRefRequired'));
      }
      if (payload.vae_ref && !isVaeRef(payload.vae_ref)) {
        throw new Error(t('settings:imageGeneration.errors.vaeRefSafeRefRequired'));
      }
      if (payload.variant && SDXL_ONLY_VARIANTS.includes(payload.variant) && payload.architecture !== 'sdxl') {
        throw new Error(t('settings:imageGeneration.errors.sdxlVariantRequired'));
      }
      const saved = isNew
        ? await api.createImageGenerationModel(payload)
        : await api.patchImageGenerationModel(values.id || '', payload);
      await onProfilesChanged(saved.id);
      await refreshStatus();
      setResult(t('settings:imageGeneration.results.profileSaved'));
    } catch (caught) {
      setError(toSettingsError(caught, t('settings:imageGeneration.errors.saveFailed')));
    } finally {
      setBusy('');
    }
  }

  async function remove() {
    if (!values.id) return;
    if (!window.confirm(t('settings:imageGeneration.confirm.deleteProfile', { name: values.name || t('settings:objectList.untitledModel') }))) return;
    setBusy('deleting');
    try {
      setError(null);
      await api.deleteImageGenerationModel(values.id);
      await onProfilesChanged();
      await refreshStatus();
      setResult(t('settings:imageGeneration.results.profileDeleted'));
    } catch (caught) {
      setError(toSettingsError(caught, t('settings:imageGeneration.errors.deleteFailed')));
    } finally {
      setBusy('');
    }
  }

  function patchValues(patch: Partial<ImageGenerationModelProfile>, options: { autoAlias?: boolean } = {}) {
    setValues((current) => {
      const next = { ...current, ...patch };
      if (isNew && !profileKeyTouched && options.autoAlias) {
        next.alias = uniqueProfileKey([next.name, finalSafeRefSegment(next.checkpoint_ref, CHECKPOINT_REF_PREFIX)], profiles, next.id, 'image-model');
      }
      return next;
    });
  }

  function selectCheckpointRef(ref: string) {
    const item = checkpointOptions.find((option) => option.ref === ref);
    patchValues({
      checkpoint_ref: ref,
      name: values.name?.trim() ? values.name : item?.name || values.name || '',
    }, { autoAlias: true });
  }

  function setArchitecture(architecture: string) {
    const nextArchitecture = architecture as ImageGenerationArchitecture;
    patchValues({
      architecture: nextArchitecture,
      variant: nextArchitecture === 'sdxl' || !SDXL_ONLY_VARIANTS.includes(currentVariant) ? currentVariant : 'base',
    });
  }

  function setVariant(variant: string) {
    const nextVariant = variant as ImageGenerationVariant;
    patchValues({
      variant: nextVariant,
      architecture: SDXL_ONLY_VARIANTS.includes(nextVariant) ? 'sdxl' : currentArchitecture,
    });
  }

  return (
    <form className="settings-detail-form" onSubmit={save}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">{profileInitials(values.name || values.alias || currentCheckpointRef || 'IG') || <Image size={18} />}</div>
          <div>
            <h2>{values.name || t('settings:imageGeneration.titles.newProfile')}</h2>
            <p>
              <code>{`key:${values.alias || 'profile_key'}`}</code>
              <code>{`arch:${currentArchitecture}`}</code>
              <span>{currentCheckpointRef || t('settings:imageGeneration.empty.noCheckpointRef')}</span>
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
            <h3>{t('settings:imageGeneration.sections.model')}</h3>
            <div className="settings-button-row">
              <button className="settings-secondary-button" type="button" onClick={() => void refreshInventory()} disabled={Boolean(busy)}>
                <RefreshCw size={14} className={busy === 'inventory' ? 'spin' : ''} />
                {busy === 'inventory' ? t('settings:imageGeneration.actions.refreshingInventory') : t('settings:imageGeneration.actions.refreshInventory')}
              </button>
            </div>
          </div>
          <div className="settings-config-form llm-profile-form">
            <TextField label={t('settings:imageGeneration.labels.name')} value={values.name || ''} onChange={(name) => patchValues({ name }, { autoAlias: true })} disabled={Boolean(busy)} />
            <label className="config-field settings-config-field">
              <span>{t('settings:imageGeneration.labels.checkpointRef')}</span>
              <select value={currentCheckpointRef} onChange={(event) => selectCheckpointRef(event.currentTarget.value)} disabled={Boolean(busy)}>
                <option value="">{checkpointOptions.length ? t('settings:imageGeneration.empty.selectCheckpointRef') : t('settings:imageGeneration.empty.noCheckpointRefs')}</option>
                {checkpointRefMissing ? <option value={currentCheckpointRef}>{t('settings:imageGeneration.labels.missingCurrentRef', { ref: currentCheckpointRef })}</option> : null}
                {checkpointOptions.map((item) => (
                  <option key={item.ref} value={item.ref} title={item.relative_path || item.ref}>
                    {item.name} ({item.ref})
                  </option>
                ))}
              </select>
              <small>{inventoryRoot ? t('settings:imageGeneration.help.inventoryRoot', { root: inventoryRoot }) : t('settings:imageGeneration.help.checkpointSafeRef')}</small>
            </label>
            <label className="config-field settings-config-field">
              <span>{t('settings:imageGeneration.labels.vaeRef')}</span>
              <select value={currentVaeRef} onChange={(event) => patchValues({ vae_ref: event.currentTarget.value || null })} disabled={Boolean(busy)}>
                <option value="">{vaeOptions.length ? t('settings:imageGeneration.empty.noVaeOverride') : t('settings:imageGeneration.empty.noVaeRefs')}</option>
                {vaeRefMissing ? <option value={currentVaeRef}>{t('settings:imageGeneration.labels.missingCurrentRef', { ref: currentVaeRef })}</option> : null}
                {vaeOptions.map((item) => (
                  <option key={item.ref} value={item.ref} title={item.relative_path || item.ref}>
                    {item.name} ({item.ref})
                  </option>
                ))}
              </select>
              <small>{t('settings:imageGeneration.help.vaeSafeRef')}</small>
            </label>
          </div>
          {checkpointRefMissing ? <p className="settings-warning-text">{t('settings:imageGeneration.warnings.checkpointRefMissing')}</p> : null}
          {checkpointRefInvalid ? <p className="settings-warning-text">{t('settings:imageGeneration.errors.checkpointRefSafeRefRequired')}</p> : null}
          {vaeRefMissing ? <p className="settings-warning-text">{t('settings:imageGeneration.warnings.vaeRefMissing')}</p> : null}
          {vaeRefInvalid ? <p className="settings-warning-text">{t('settings:imageGeneration.errors.vaeRefSafeRefRequired')}</p> : null}
          {inventoryWarnings.map((warning) => <p key={warning} className="settings-warning-text">{warning}</p>)}
        </section>
        <section className="detail-section">
          <h3>{t('settings:imageGeneration.sections.profile')}</h3>
          <div className="settings-config-form llm-profile-form">
            <TextField label={t('settings:imageGeneration.labels.notes')} value={values.notes || ''} onChange={(notes) => patchValues({ notes })} disabled={Boolean(busy)} textarea />
          </div>
        </section>
        <section className="detail-section">
          <h3>{t('settings:imageGeneration.sections.runtime')}</h3>
          <div className="settings-config-form llm-profile-form">
            <SelectField label={t('settings:imageGeneration.labels.architecture')} value={currentArchitecture} options={ARCHITECTURES} labelPrefix="settings:imageGeneration.architectures" onChange={setArchitecture} disabled={Boolean(busy)} />
            <SelectField label={t('settings:imageGeneration.labels.variant')} value={currentVariant} options={VARIANTS} labelPrefix="settings:imageGeneration.variants" onChange={setVariant} disabled={Boolean(busy)} />
            <SelectField label={t('settings:imageGeneration.labels.dtype')} value={values.dtype || 'auto'} options={DTYPES} labelPrefix="settings:imageGeneration.dtypes" onChange={(dtype) => patchValues({ dtype: dtype as ImageGenerationDtype })} disabled={Boolean(busy)} />
            <SelectField label={t('settings:imageGeneration.labels.device')} value={values.device || 'auto'} options={DEVICES} labelPrefix="settings:imageGeneration.devices" onChange={(device) => patchValues({ device: device as ImageGenerationDevice })} disabled={Boolean(busy)} />
            <NumberField label={t('settings:imageGeneration.labels.clipSkip')} value={values.clip_skip ?? null} onChange={(clip_skip) => patchValues({ clip_skip })} disabled={Boolean(busy)} />
          </div>
          {SDXL_ONLY_VARIANTS.includes(currentVariant) && currentArchitecture !== 'sdxl' ? <p className="settings-warning-text">{t('settings:imageGeneration.errors.sdxlVariantRequired')}</p> : null}
        </section>
        <section className="detail-section">
          <h3>{t('settings:imageGeneration.sections.tasks')}</h3>
          <div className="llm-profile-flags">
            <ToggleSwitch checked label={t('settings:imageGeneration.tasks.txt2img')} disabled onChange={() => undefined} />
          </div>
          <p className="settings-muted-copy">{t('settings:imageGeneration.help.tasksReadOnly')}</p>
        </section>
        <section className="detail-section">
          <div className="detail-section-heading">
            <h3>{t('settings:imageGeneration.sections.status')}</h3>
            <div className="settings-button-row">
              <button className="settings-secondary-button" type="button" onClick={() => void refreshStatus()} disabled={Boolean(busy)}>
                <RefreshCw size={14} className={busy === 'status' ? 'spin' : ''} />
                {busy === 'status' ? t('settings:imageGeneration.actions.refreshingStatus') : t('settings:imageGeneration.actions.refreshStatus')}
              </button>
              <button className="settings-secondary-button" type="button" onClick={() => void unloadCache(false)} disabled={Boolean(busy)}>
                <Power size={14} />
                {t('settings:imageGeneration.actions.unloadCache')}
              </button>
            </div>
          </div>
          <dl className="settings-definition-grid compact">
            <Metric label={t('settings:imageGeneration.status.backend')} value={runtimeStatus?.runtime.backend || t('status:common.unavailable', { ns: 'status' })} />
            <Metric label={t('settings:imageGeneration.status.realGeneration')} value={runtimeStatus ? (runtimeStatus.runtime.real_generation ? t('status:common.yes', { ns: 'status' }) : t('status:common.no', { ns: 'status' })) : t('status:common.unavailable', { ns: 'status' })} />
            <Metric label={t('settings:imageGeneration.status.profiles')} value={runtimeStatus ? t('settings:imageGeneration.status.enabledCount', { enabled: runtimeStatus.profiles_enabled, total: runtimeStatus.profiles_total }) : t('status:common.unavailable', { ns: 'status' })} />
            <Metric label={t('settings:imageGeneration.status.queue')} value={runtimeStatus?.queue ? `${runtimeStatus.queue.active_count} / ${runtimeStatus.queue.queued_count}` : t('status:common.unavailable', { ns: 'status' })} />
            <Metric label={t('settings:imageGeneration.status.cache')} value={runtimeStatus ? String(runtimeStatus.cache?.cached_profiles ?? 0) : t('status:common.unavailable', { ns: 'status' })} />
          </dl>
          <p className="settings-muted-copy">{t('settings:imageGeneration.help.fakeRuntime')}</p>
          {unloadResult ? <p className="settings-muted-copy">{t(`settings:imageGeneration.unloadStatus.${unloadResult.status}`, { defaultValue: unloadResult.message })}</p> : null}
          {!isNew ? (
            <div className="settings-button-row">
              <button className="settings-secondary-button" type="button" onClick={() => void unloadCache(true)} disabled={Boolean(busy)}>
                <Power size={14} />
                {t('settings:imageGeneration.actions.unloadProfileCache')}
              </button>
            </div>
          ) : null}
        </section>
        <section className="detail-section">
          <h3>{t('settings:imageGeneration.sections.advanced')}</h3>
          <div className="settings-config-form llm-profile-form">
            <TextField
              label={t('settings:imageGeneration.labels.profileKey')}
              value={values.alias || ''}
              onChange={(alias) => {
                setProfileKeyTouched(true);
                patchValues({ alias: sanitizeProfileKey(alias) });
              }}
              disabled={Boolean(busy)}
              help={t('settings:imageGeneration.help.profileKey')}
            />
          </div>
          <label className="config-field settings-config-field">
            <span>{t('settings:imageGeneration.labels.metadataJson')}</span>
            <textarea rows={8} value={metadataText} onChange={(event) => setMetadataText(event.currentTarget.value)} disabled={Boolean(busy)} />
            <small>{t('settings:imageGeneration.help.metadataJson')}</small>
          </label>
          {!parsedMetadata.ok ? <p className="settings-warning-text">{t('settings:imageGeneration.errors.invalidMetadataJson')}</p> : null}
        </section>
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
        min={1}
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

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd title={value}>{value}</dd>
    </div>
  );
}

function buildImageGenerationPayload(values: Partial<ImageGenerationModelProfile>, metadata: Record<string, unknown>): ImageGenerationModelProfileInput {
  return {
    name: values.name ?? '',
    alias: values.alias ?? '',
    description: values.description ?? '',
    notes: values.notes ?? '',
    enabled: values.enabled ?? true,
    architecture: values.architecture || 'sdxl',
    variant: values.variant || 'base',
    checkpoint_ref: values.checkpoint_ref ?? '',
    vae_ref: optionalString(values.vae_ref),
    dtype: values.dtype || 'auto',
    device: values.device || 'auto',
    clip_skip: optionalNumber(values.clip_skip),
    supported_tasks: ['txt2img'],
    metadata,
  };
}

function optionalString(value: string | null | undefined): string | null {
  const trimmed = String(value || '').trim();
  return trimmed ? trimmed : null;
}

function optionalNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const numberValue = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
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

function isCheckpointRef(value: string): boolean {
  return isImageGenerationRef(value, CHECKPOINT_REF_PREFIX);
}

function isVaeRef(value: string): boolean {
  return isImageGenerationRef(value, VAE_REF_PREFIX);
}

function isImageGenerationRef(value: string, prefix: string): boolean {
  const text = String(value || '').trim();
  if (!text.startsWith(prefix) || text.includes('\\')) return false;
  const remainder = text.slice(prefix.length);
  if (!remainder) return false;
  return remainder.split('/').every((part) => part && part !== '.' && part !== '..');
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
