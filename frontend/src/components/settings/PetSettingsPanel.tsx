import { PawPrint, RefreshCw, RotateCcw, Save, Search, Trash2, Upload } from 'lucide-react';
import { DragEvent, FormEvent, useEffect, useMemo, useState, type CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';
import { api, joinApiUrl, API_BASE_URL } from '../../api/client';
import type { PetBubbleTexts, PetCommandTexts, PetItem, PetSettings } from '../../types';
import { PetSprite, type PetSpriteState } from '../PetSprite';
import { DetailTabs } from './DetailTabs';
import { SettingsApiError, toSettingsError, type SettingsErrorValue } from './SettingsApiError';
import { ToggleSwitch } from './ToggleSwitch';

const BUBBLE_TEXT_KEYS: (keyof PetBubbleTexts)[] = [
  'idle',
  'waiting',
  'done',
  'failed',
  'cancelled',
  'interrupted',
  'wake',
  'tuck',
  'status',
  'select',
  'reload',
  'no_pet',
  'import_success',
  'import_failed',
  'delete_success',
  'delete_failed',
];

const COMMAND_TEXT_KEYS: (keyof PetCommandTexts)[] = [
  'wake',
  'tuck',
  'select',
  'status',
  'reload',
  'no_pet',
  'select_missing',
];

const DEFAULT_BUBBLE_TEXTS: PetBubbleTexts = {
  idle: '',
  waiting: 'Waiting',
  done: 'Done',
  failed: 'Failed',
  cancelled: 'Cancelled',
  interrupted: 'Interrupted',
  wake: 'Wake',
  tuck: 'Tuck',
  status: 'Status',
  select: 'Selected',
  reload: 'Scan complete',
  no_pet: 'No pet available',
  import_success: 'Import complete',
  import_failed: 'Import failed',
  delete_success: 'Deleted',
  delete_failed: 'Delete failed',
};

const DEFAULT_COMMAND_TEXTS: PetCommandTexts = {
  wake: 'Woke {pet.display_name}',
  tuck: '{pet.display_name} is tucked away',
  select: 'Selected {pet.display_name}.\n{pet.description}',
  status: 'Current pet: {pet.display_name}',
  reload: 'Scanned pets: {valid_count} valid, {invalid_count} invalid',
  no_pet: 'No pet available',
  select_missing: 'Pet not found: {pet_id}',
};

const PET_PREVIEW_STATES: PetSpriteState[] = ['idle', 'waving', 'jumping', 'waiting', 'running', 'review', 'failed'];

const DEFAULT_SETTINGS: PetSettings = {
  pet_enabled: true,
  default_pet_id: '',
  pet_scale: 0.5,
  show_status_bubble: true,
  bubble_offset_x: 12,
  bubble_offset_y: -12,
  jump_on_hover: true,
  running_prefix: 'Running',
  position: { mode: 'default', x: null, y: null },
  bubble_texts: DEFAULT_BUBBLE_TEXTS,
  command_texts: DEFAULT_COMMAND_TEXTS,
};

export function PetSettingsDetail({
  activeTab,
  onTabChange,
  onDirtyChange,
}: {
  activeTab: string;
  onTabChange: (tab: string) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation(['pet', 'common']);
  const normalizedTab = activeTab === 'pet-list' ? 'pet-list' : 'config';
  const [settings, setSettings] = useState<PetSettings | null>(null);
  const [values, setValues] = useState<PetSettings | null>(null);
  const [pets, setPets] = useState<PetItem[]>([]);
  const [busy, setBusy] = useState('');
  const [saved, setSaved] = useState(false);
  const [notice, setNotice] = useState('');
  const [localError, setLocalError] = useState<SettingsErrorValue | null>(null);

  const validPets = useMemo(() => pets.filter((pet) => pet.valid), [pets]);
  const dirty = Boolean(values && settings && JSON.stringify(values) !== JSON.stringify(settings));

  useEffect(() => {
    void refreshAll().catch(() => undefined);
  }, []);

  useEffect(() => {
    onDirtyChange(normalizedTab === 'config' && dirty);
  }, [dirty, normalizedTab, onDirtyChange]);

  async function refreshAll() {
    setBusy('refresh');
    try {
      setLocalError(null);
      const [settingsResponse, petsResponse] = await Promise.all([api.getPetSettings(), api.listPets()]);
      const nextSettings = normalizeSettings(settingsResponse.settings);
      setSettings(nextSettings);
      setValues(nextSettings);
      setPets(petsResponse.pets);
    } catch (error) {
      setLocalError(toSettingsError(error, t('pet:errors.load')));
    } finally {
      setBusy('');
    }
  }

  async function refreshPets() {
    const petsResponse = await api.listPets();
    setPets(petsResponse.pets);
    return petsResponse.pets;
  }

  async function save(event?: FormEvent) {
    event?.preventDefault();
    if (!values) return;
    setBusy('save');
    try {
      setLocalError(null);
      const response = await api.updatePetSettings(values);
      const nextSettings = normalizeSettings(response.settings);
      setSettings(nextSettings);
      setValues(nextSettings);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 1400);
    } catch (error) {
      setLocalError(toSettingsError(error, t('pet:errors.save')));
    } finally {
      setBusy('');
    }
  }

  async function resetPosition() {
    if (!values) return;
    setBusy('reset');
    try {
      setLocalError(null);
      const response = await api.updatePetSettings({ position: DEFAULT_SETTINGS.position });
      const nextSettings = normalizeSettings(response.settings);
      setSettings(nextSettings);
      setValues(nextSettings);
      setNotice(t('pet:notice.positionReset'));
      window.setTimeout(() => setNotice(''), 1400);
    } catch (error) {
      setLocalError(toSettingsError(error, t('pet:errors.resetPosition')));
    } finally {
      setBusy('');
    }
  }

  async function scanPets() {
    setBusy('scan');
    try {
      setLocalError(null);
      const response = await api.scanPets();
      setPets(response.pets);
      setNotice(values?.bubble_texts.reload || DEFAULT_BUBBLE_TEXTS.reload);
      window.setTimeout(() => setNotice(''), 1600);
    } catch (error) {
      setLocalError(toSettingsError(error, t('pet:errors.scan')));
    } finally {
      setBusy('');
    }
  }

  async function deletePet(pet: PetItem) {
    if (!window.confirm(t('pet:confirm.delete', { name: pet.display_name || pet.id }))) return;
    setBusy(`delete:${pet.id}`);
    try {
      setLocalError(null);
      await api.deletePet(pet.id);
      const nextPets = await refreshPets();
      if (values?.default_pet_id === pet.id) {
        const fallbackPetId = nextPets.find((item) => item.valid)?.id || '';
        const response = await api.updatePetSettings({ default_pet_id: fallbackPetId });
        const nextSettings = normalizeSettings(response.settings);
        setSettings(nextSettings);
        setValues(nextSettings);
      }
      setNotice(values?.bubble_texts.delete_success || DEFAULT_BUBBLE_TEXTS.delete_success);
      window.setTimeout(() => setNotice(''), 1600);
    } catch (error) {
      setLocalError(toSettingsError(error, values?.bubble_texts.delete_failed || DEFAULT_BUBBLE_TEXTS.delete_failed));
    } finally {
      setBusy('');
    }
  }

  async function importPet(files: File[]) {
    const names = files.map((file) => file.name);
    const allowed = new Set(['pet.json', 'spritesheet.webp']);
    const unexpected = names.filter((name) => !allowed.has(name));
    const petJson = files.find((file) => file.name === 'pet.json');
    const spritesheet = files.find((file) => file.name === 'spritesheet.webp');
    if (unexpected.length || !petJson || !spritesheet) {
      setLocalError({
        code: 'PET_IMPORT_FILES_REQUIRED',
        message: t('pet:errors.importFilesRequired'),
        details: { received: names },
      });
      return;
    }

    setBusy('import');
    try {
      setLocalError(null);
      const response = await api.importPet(petJson, spritesheet);
      setPets(response.pets);
      const nextSettings = response.settings
        ? normalizeSettings(response.settings)
        : normalizeSettings((await api.getPetSettings()).settings);
      setSettings(nextSettings);
      setValues(nextSettings);
      setNotice(nextSettings.bubble_texts.import_success || DEFAULT_BUBBLE_TEXTS.import_success);
      window.setTimeout(() => setNotice(''), 1800);
    } catch (error) {
      setLocalError(toSettingsError(error, values?.bubble_texts.import_failed || DEFAULT_BUBBLE_TEXTS.import_failed));
    } finally {
      setBusy('');
    }
  }

  function setValue<K extends keyof PetSettings>(key: K, value: PetSettings[K]) {
    setValues((current) => (current ? { ...current, [key]: value } : current));
  }

  function setBubbleText(key: keyof PetBubbleTexts, text: string) {
    setValues((current) => current ? { ...current, bubble_texts: { ...current.bubble_texts, [key]: text } } : current);
  }

  function setCommandText(key: keyof PetCommandTexts, text: string) {
    setValues((current) => current ? { ...current, command_texts: { ...current.command_texts, [key]: text } } : current);
  }

  return (
    <form className="settings-detail-form" onSubmit={save}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">
            <PawPrint size={18} />
          </div>
          <div>
            <h2>{t('pet:title')}</h2>
            <p>
              <code>pet</code>
              <span>{t('pet:subtitle')}</span>
            </p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {notice ? <span className="settings-badge success">{notice}</span> : null}
          {saved ? <span className="settings-badge success">{t('common:saved')}</span> : null}
          {normalizedTab === 'config' && dirty ? (
            <button className="settings-primary-button" type="submit" disabled={Boolean(busy)}>
              <Save size={14} />
              {busy === 'save' ? t('common:saving') : t('common:save')}
            </button>
          ) : null}
        </div>
      </header>
      <DetailTabs
        tabs={[
          { id: 'config', label: t('pet:tabs.config') },
          { id: 'pet-list', label: t('pet:tabs.petList') },
        ]}
        activeTab={normalizedTab}
        onChange={onTabChange}
      />
      <div className="settings-detail-body">
        {localError ? <SettingsApiError error={localError} /> : null}
        {!values ? (
          <div className="settings-empty-state compact">{busy ? t('pet:empty.loading') : t('pet:empty.unavailable')}</div>
        ) : normalizedTab === 'config' ? (
          <PetConfigTab
            values={values}
            validPets={validPets}
            busy={busy}
            onSetValue={setValue}
            onSetBubbleText={setBubbleText}
            onSetCommandText={setCommandText}
            onResetPosition={resetPosition}
            onScanPets={scanPets}
            onImportPet={importPet}
          />
        ) : (
          <PetListTab pets={pets} busy={busy} onScanPets={scanPets} onDeletePet={deletePet} />
        )}
      </div>
    </form>
  );
}

function PetConfigTab({
  values,
  validPets,
  busy,
  onSetValue,
  onSetBubbleText,
  onSetCommandText,
  onResetPosition,
  onScanPets,
  onImportPet,
}: {
  values: PetSettings;
  validPets: PetItem[];
  busy: string;
  onSetValue: <K extends keyof PetSettings>(key: K, value: PetSettings[K]) => void;
  onSetBubbleText: (key: keyof PetBubbleTexts, text: string) => void;
  onSetCommandText: (key: keyof PetCommandTexts, text: string) => void;
  onResetPosition: () => void;
  onScanPets: () => void;
  onImportPet: (files: File[]) => void;
}) {
  const { t } = useTranslation(['pet', 'common']);
  const [dragging, setDragging] = useState(false);
  const [previewState, setPreviewState] = useState<PetSpriteState>('idle');

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const files = Array.from(event.dataTransfer.files || []);
    void onImportPet(files);
  }

  return (
    <>
      <section className="detail-section">
        <div className="detail-section-heading"><h3>{t('pet:sections.general')}</h3></div>
        <div className="pet-general-layout">
          <PetPreviewPanel
            values={values}
            validPets={validPets}
            previewState={previewState}
            onPreviewStateChange={setPreviewState}
          />
          <div className="pet-general-fields">
            <label className="config-field settings-config-field boolean-field">
              <span>{t('pet:labels.enablePet')}</span>
              <ToggleSwitch checked={values.pet_enabled} onChange={(checked) => onSetValue('pet_enabled', checked)} />
            </label>
            <div className="settings-detail-grid">
              <label className="config-field settings-config-field">
                <span>{t('pet:labels.defaultPet')}</span>
                <select value={values.default_pet_id} disabled={!validPets.length} onChange={(event) => onSetValue('default_pet_id', event.currentTarget.value)}>
                  {!validPets.length ? <option value="">{t('pet:empty.noValidPets')}</option> : <option value="">{t('pet:empty.noDefaultPet')}</option>}
                  {validPets.map((pet) => (
                    <option key={pet.id} value={pet.id}>{pet.display_name || pet.id}</option>
                  ))}
                </select>
              </label>
              <label className="config-field settings-config-field pet-scale-field">
                <span>{t('pet:labels.scale')}</span>
                <div className="pet-scale-row">
                  <input type="range" min="0.5" max="2" step="0.05" value={values.pet_scale} onChange={(event) => onSetValue('pet_scale', Number(event.currentTarget.value))} />
                  <input type="number" min="0.5" max="2" step="0.05" value={values.pet_scale} onChange={(event) => onSetValue('pet_scale', Number(event.currentTarget.value))} />
                </div>
              </label>
            </div>
            <label className="config-field settings-config-field boolean-field">
              <span>{t('pet:labels.showStatusBubble')}</span>
              <ToggleSwitch checked={values.show_status_bubble} onChange={(checked) => onSetValue('show_status_bubble', checked)} />
            </label>
            <div className="settings-detail-grid">
              <label className="config-field settings-config-field">
                <span>{t('pet:labels.bubbleOffsetX')}</span>
                <input
                  type="number"
                  min="-240"
                  max="240"
                  step="1"
                  value={values.bubble_offset_x}
                  onChange={(event) => onSetValue('bubble_offset_x', clampNumber(Number(event.currentTarget.value), -240, 240))}
                />
              </label>
              <label className="config-field settings-config-field">
                <span>{t('pet:labels.bubbleOffsetY')}</span>
                <input
                  type="number"
                  min="-240"
                  max="240"
                  step="1"
                  value={values.bubble_offset_y}
                  onChange={(event) => onSetValue('bubble_offset_y', clampNumber(Number(event.currentTarget.value), -240, 240))}
                />
              </label>
            </div>
            <div className="settings-button-row">
              <button className="settings-secondary-button" type="button" disabled={Boolean(busy)} onClick={onResetPosition}>
                <RotateCcw size={14} />
                {t('pet:buttons.resetPosition')}
              </button>
            </div>
          </div>
        </div>
      </section>

      <section className="detail-section">
        <div className="detail-section-heading"><h3>{t('pet:sections.library')}</h3></div>
        <div className="settings-button-row">
          <button className="settings-secondary-button" type="button" disabled={Boolean(busy)} onClick={onScanPets}>
            <Search size={14} />
            {busy === 'scan' ? t('pet:buttons.scanning') : t('pet:buttons.scanPets')}
          </button>
          <button className="settings-secondary-button" type="button" disabled={busy === 'import'}>
            <Upload size={14} />
            {busy === 'import' ? t('pet:buttons.importing') : t('pet:buttons.importPet')}
          </button>
        </div>
        <div
          className={`pet-import-dropzone ${dragging ? 'dragging' : ''}`}
          onDragEnter={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragOver={(event) => {
            event.preventDefault();
            event.dataTransfer.dropEffect = 'copy';
          }}
          onDragLeave={(event) => {
            if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
            setDragging(false);
          }}
          onDrop={handleDrop}
        >
          <Upload size={18} />
          <strong>{t('pet:import.dropFiles')}</strong>
          <span>{t('pet:import.acceptedFiles')}</span>
          <small>{t('pet:import.savedUnder')}</small>
        </div>
      </section>

      <section className="detail-section">
        <div className="detail-section-heading"><h3>{t('pet:sections.runningBubble')}</h3></div>
        <label className="config-field settings-config-field">
          <span>{t('pet:labels.runningPrefix')}</span>
          <input type="text" value={values.running_prefix} onChange={(event) => onSetValue('running_prefix', event.currentTarget.value)} />
          <small>{t('pet:help.runningPrefix')}</small>
        </label>
        <div className="settings-chip-row">
          <small>{t('pet:help.example', { text: `${values.running_prefix || 'Running'} Calling model` })}</small>
          <small>{t('pet:help.example', { text: `${values.running_prefix || 'Running'} Searching knowledge base` })}</small>
        </div>
      </section>

      <section className="detail-section">
        <div className="detail-section-heading"><h3>{t('pet:sections.statusBubbleTexts')}</h3></div>
        <div className="pet-bubble-grid">
          {BUBBLE_TEXT_KEYS.map((key) => (
            <label key={key} className="config-field settings-config-field">
              <span>{key}</span>
              <input type="text" value={values.bubble_texts[key]} onChange={(event) => onSetBubbleText(key, event.currentTarget.value)} />
            </label>
          ))}
        </div>
      </section>

      <section className="detail-section">
        <div className="detail-section-heading"><h3>{t('pet:sections.commandTexts')}</h3></div>
        <div className="pet-bubble-grid">
          {COMMAND_TEXT_KEYS.map((key) => (
            <label key={key} className="config-field settings-config-field">
              <span>{key}</span>
              <textarea rows={key === 'select' ? 3 : 2} value={values.command_texts[key]} onChange={(event) => onSetCommandText(key, event.currentTarget.value)} />
            </label>
          ))}
        </div>
      </section>

      <section className="detail-section">
        <div className="detail-section-heading"><h3>{t('pet:sections.interaction')}</h3></div>
        <label className="config-field settings-config-field boolean-field">
          <span>{t('pet:labels.jumpOnHover')}</span>
          <ToggleSwitch checked={values.jump_on_hover} onChange={(checked) => onSetValue('jump_on_hover', checked)} />
          <small>{t('pet:help.jumpOnHover')}</small>
        </label>
      </section>
    </>
  );
}

function PetPreviewPanel({
  values,
  validPets,
  previewState,
  onPreviewStateChange,
}: {
  values: PetSettings;
  validPets: PetItem[];
  previewState: PetSpriteState;
  onPreviewStateChange: (state: PetSpriteState) => void;
}) {
  const { t } = useTranslation(['pet']);
  const renderablePets = useMemo(() => validPets.filter((pet) => pet.spritesheet_url), [validPets]);
  const pet = useMemo(() => {
    if (!renderablePets.length) return null;
    return renderablePets.find((item) => item.id === values.default_pet_id) || renderablePets[0];
  }, [renderablePets, values.default_pet_id]);
  const spriteUrl = pet?.spritesheet_url ? joinApiUrl(API_BASE_URL, pet.spritesheet_url) : '';
  const petName = pet?.display_name || pet?.id || '';
  const scale = clampFloat(Number(values.pet_scale), 0.5, 2);

  return (
    <div className="pet-preview-panel" aria-label={t('pet:labels.preview')}>
      <div className="pet-preview-header">
        <div>
          <strong>{t('pet:labels.preview')}</strong>
          <span>{pet ? petName : t('pet:empty.noValidPetSelected')}</span>
        </div>
        <label className="pet-preview-state-select">
          <span>{t('pet:labels.state')}</span>
          <select value={previewState} onChange={(event) => onPreviewStateChange(event.currentTarget.value as PetSpriteState)}>
            {PET_PREVIEW_STATES.map((state) => (
              <option key={state} value={state}>{state}</option>
            ))}
          </select>
        </label>
      </div>
      {pet && spriteUrl ? (
        <>
          <div className="pet-preview-scene">
            <div
              className="pet-preview-stage"
              style={{
                '--pet-bubble-offset-x': `${values.bubble_offset_x}px`,
                '--pet-bubble-offset-y': `${values.bubble_offset_y}px`,
              } as CSSProperties}
              aria-label={petName}
              title={petName}
            >
              {values.show_status_bubble ? <div className="pet-status-bubble pet-preview-bubble">{t('pet:preview.bubble', { name: petName })}</div> : null}
              <PetSprite spritesheetUrl={spriteUrl} state={previewState} scale={scale} className="pet-sprite" />
            </div>
          </div>
          {pet.description ? <p className="pet-preview-description">{pet.description}</p> : null}
        </>
      ) : (
        <div className="settings-empty-state compact pet-preview-empty">{t('pet:empty.noValidPetSelected')}</div>
      )}
    </div>
  );
}

function PetListTab({
  pets,
  busy,
  onScanPets,
  onDeletePet,
}: {
  pets: PetItem[];
  busy: string;
  onScanPets: () => void;
  onDeletePet: (pet: PetItem) => void;
}) {
  const { t } = useTranslation(['pet']);
  return (
    <section className="detail-section">
      <div className="detail-section-heading">
        <h3>{t('pet:sections.petList')}</h3>
        <button className="settings-secondary-button" type="button" disabled={Boolean(busy)} onClick={onScanPets}>
          <RefreshCw size={14} />
          {busy === 'scan' ? t('pet:buttons.scanning') : t('pet:buttons.scanPets')}
        </button>
      </div>
      {pets.length ? (
        <div className="pet-list">
          {pets.map((pet) => (
            <PetListItem key={pet.id} pet={pet} busy={busy} onDeletePet={onDeletePet} />
          ))}
        </div>
      ) : (
        <div className="settings-empty-state compact">{t('pet:empty.noPetsFound')}</div>
      )}
    </section>
  );
}

function PetListItem({ pet, busy, onDeletePet }: { pet: PetItem; busy: string; onDeletePet: (pet: PetItem) => void }) {
  const { t } = useTranslation(['pet', 'common']);
  const canDelete = pet.can_delete && !pet.is_builtin;
  const deleting = busy === `delete:${pet.id}`;
  const spriteUrl = pet.valid && pet.spritesheet_url ? joinApiUrl(API_BASE_URL, pet.spritesheet_url) : '';
  return (
    <div className={`pet-list-item ${pet.valid ? '' : 'invalid'}`}>
      {spriteUrl ? (
        <div className="pet-avatar pet-avatar-animated" aria-hidden="true">
          <PetSprite spritesheetUrl={spriteUrl} state="idle" scale={0.25} />
        </div>
      ) : (
        <div className="pet-avatar pet-avatar-placeholder" aria-hidden="true"><PawPrint size={18} /></div>
      )}
      <div className="pet-list-copy">
        <strong>{pet.display_name || pet.id}</strong>
        <span>{pet.description || t('pet:empty.noDescription')}</span>
        <div className="pet-list-meta">
          <span>{pet.source}</span>
          <span className={pet.valid ? 'settings-badge success' : 'settings-badge warning'}>{pet.status}</span>
          {!pet.valid && pet.errors?.length ? <small>{pet.errors.join('; ')}</small> : null}
        </div>
      </div>
      {canDelete ? (
        <button className="settings-secondary-button danger pet-delete-button" type="button" disabled={deleting} onClick={() => onDeletePet(pet)}>
          <Trash2 size={14} />
          {deleting ? t('pet:buttons.deleting') : t('common:delete')}
        </button>
      ) : null}
    </div>
  );
}

function normalizeSettings(value: Partial<PetSettings> | null | undefined): PetSettings {
  const settings = { ...DEFAULT_SETTINGS, ...(value || {}) };
  return {
    ...settings,
    pet_enabled: Boolean(settings.pet_enabled),
    default_pet_id: typeof settings.default_pet_id === 'string' ? settings.default_pet_id : '',
    pet_scale: typeof settings.pet_scale === 'number' ? settings.pet_scale : Number(settings.pet_scale) || 0.5,
    show_status_bubble: Boolean(settings.show_status_bubble),
    bubble_offset_x: clampNumber(Number(settings.bubble_offset_x ?? 12), -240, 240),
    bubble_offset_y: clampNumber(Number(settings.bubble_offset_y ?? -12), -240, 240),
    jump_on_hover: Boolean(settings.jump_on_hover),
    running_prefix: typeof settings.running_prefix === 'string' ? settings.running_prefix : DEFAULT_SETTINGS.running_prefix,
    position: {
      mode: typeof settings.position?.mode === 'string' ? settings.position.mode : 'default',
      x: typeof settings.position?.x === 'number' ? settings.position.x : null,
      y: typeof settings.position?.y === 'number' ? settings.position.y : null,
    },
    bubble_texts: { ...DEFAULT_BUBBLE_TEXTS, ...(settings.bubble_texts || {}) },
    command_texts: { ...DEFAULT_COMMAND_TEXTS, ...(settings.command_texts || {}) },
  };
}

function clampNumber(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, Math.round(value)));
}

function clampFloat(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, value));
}

