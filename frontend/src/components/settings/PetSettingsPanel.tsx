import { PawPrint, RefreshCw, RotateCcw, Save, Search, Trash2, Upload } from 'lucide-react';
import { DragEvent, FormEvent, useEffect, useMemo, useState } from 'react';
import { api, joinApiUrl, API_BASE_URL } from '../../api/client';
import type { PetBubbleTexts, PetItem, PetSettings } from '../../types';
import { PetSprite } from '../PetSprite';
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

const DEFAULT_SETTINGS: PetSettings = {
  pet_enabled: true,
  default_pet_id: '',
  pet_scale: 1,
  show_status_bubble: true,
  bubble_offset_x: 12,
  bubble_offset_y: -12,
  jump_on_hover: true,
  running_prefix: 'Running',
  position: { mode: 'default', x: null, y: null },
  bubble_texts: DEFAULT_BUBBLE_TEXTS,
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
      setLocalError(toSettingsError(error, 'Failed to load pet settings.'));
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
      setLocalError(toSettingsError(error, 'Failed to save pet settings.'));
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
      setNotice('Position reset');
      window.setTimeout(() => setNotice(''), 1400);
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to reset pet position.'));
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
      setLocalError(toSettingsError(error, 'Failed to scan pets.'));
    } finally {
      setBusy('');
    }
  }

  async function deletePet(pet: PetItem) {
    if (!window.confirm(`Delete pet "${pet.display_name || pet.id}"?`)) return;
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
        message: 'Drop exactly pet.json and spritesheet.webp.',
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

  return (
    <form className="settings-detail-form" onSubmit={save}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">
            <PawPrint size={18} />
          </div>
          <div>
            <h2>Pet</h2>
            <p>
              <code>pet</code>
              <span>appearance capability settings</span>
            </p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {notice ? <span className="settings-badge success">{notice}</span> : null}
          {saved ? <span className="settings-badge success">Saved</span> : null}
          {normalizedTab === 'config' && dirty ? (
            <button className="settings-primary-button" type="submit" disabled={Boolean(busy)}>
              <Save size={14} />
              {busy === 'save' ? 'Saving...' : 'Save'}
            </button>
          ) : null}
        </div>
      </header>
      <DetailTabs
        tabs={[
          { id: 'config', label: 'Config' },
          { id: 'pet-list', label: 'Pet List' },
        ]}
        activeTab={normalizedTab}
        onChange={onTabChange}
      />
      <div className="settings-detail-body">
        {localError ? <SettingsApiError error={localError} /> : null}
        {!values ? (
          <div className="settings-empty-state compact">{busy ? 'Loading pet settings.' : 'Pet settings unavailable.'}</div>
        ) : normalizedTab === 'config' ? (
          <PetConfigTab
            values={values}
            validPets={validPets}
            busy={busy}
            onSetValue={setValue}
            onSetBubbleText={setBubbleText}
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
  onResetPosition,
  onScanPets,
  onImportPet,
}: {
  values: PetSettings;
  validPets: PetItem[];
  busy: string;
  onSetValue: <K extends keyof PetSettings>(key: K, value: PetSettings[K]) => void;
  onSetBubbleText: (key: keyof PetBubbleTexts, text: string) => void;
  onResetPosition: () => void;
  onScanPets: () => void;
  onImportPet: (files: File[]) => void;
}) {
  const [dragging, setDragging] = useState(false);

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const files = Array.from(event.dataTransfer.files || []);
    void onImportPet(files);
  }

  return (
    <>
      <section className="detail-section">
        <div className="detail-section-heading"><h3>General</h3></div>
        <label className="config-field settings-config-field boolean-field">
          <span>Enable Pet</span>
          <ToggleSwitch checked={values.pet_enabled} onChange={(checked) => onSetValue('pet_enabled', checked)} />
        </label>
        <div className="settings-detail-grid">
          <label className="config-field settings-config-field">
            <span>Default Pet</span>
            <select value={values.default_pet_id} disabled={!validPets.length} onChange={(event) => onSetValue('default_pet_id', event.currentTarget.value)}>
              {!validPets.length ? <option value="">No valid pets</option> : <option value="">No default pet</option>}
              {validPets.map((pet) => (
                <option key={pet.id} value={pet.id}>{pet.display_name || pet.id}</option>
              ))}
            </select>
          </label>
          <label className="config-field settings-config-field pet-scale-field">
            <span>Scale</span>
            <div className="pet-scale-row">
              <input type="range" min="0.5" max="2" step="0.05" value={values.pet_scale} onChange={(event) => onSetValue('pet_scale', Number(event.currentTarget.value))} />
              <input type="number" min="0.5" max="2" step="0.05" value={values.pet_scale} onChange={(event) => onSetValue('pet_scale', Number(event.currentTarget.value))} />
            </div>
          </label>
        </div>
        <label className="config-field settings-config-field boolean-field">
          <span>Show Status Bubble</span>
          <ToggleSwitch checked={values.show_status_bubble} onChange={(checked) => onSetValue('show_status_bubble', checked)} />
        </label>
        <div className="settings-detail-grid">
          <label className="config-field settings-config-field">
            <span>Bubble Offset X</span>
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
            <span>Bubble Offset Y</span>
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
            Reset Position
          </button>
        </div>
      </section>

      <section className="detail-section">
        <div className="detail-section-heading"><h3>Pet Library</h3></div>
        <div className="settings-button-row">
          <button className="settings-secondary-button" type="button" disabled={Boolean(busy)} onClick={onScanPets}>
            <Search size={14} />
            {busy === 'scan' ? 'Scanning...' : 'Scan Pets'}
          </button>
          <button className="settings-secondary-button" type="button" disabled={busy === 'import'}>
            <Upload size={14} />
            {busy === 'import' ? 'Importing...' : 'Import Pet'}
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
          <strong>Drop pet.json and spritesheet.webp</strong>
          <span>Only Codex-compatible pet files with these exact names are accepted.</span>
          <small>Imported pets are saved under <code>data/pet/&lt;pet_id&gt;/</code> and selected as the default pet.</small>
        </div>
      </section>

      <section className="detail-section">
        <div className="detail-section-heading"><h3>Running Bubble</h3></div>
        <label className="config-field settings-config-field">
          <span>Running Prefix</span>
          <input type="text" value={values.running_prefix} onChange={(event) => onSetValue('running_prefix', event.currentTarget.value)} />
          <small>Running status text is built from running_prefix + task. The task is supplied by later run step integration.</small>
        </label>
        <div className="settings-chip-row">
          <small>Example: {values.running_prefix || 'Running'} Calling model</small>
          <small>Example: {values.running_prefix || 'Running'} Searching knowledge base</small>
        </div>
      </section>

      <section className="detail-section">
        <div className="detail-section-heading"><h3>Status Bubble Texts</h3></div>
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
        <div className="detail-section-heading"><h3>Interaction</h3></div>
        <label className="config-field settings-config-field boolean-field">
          <span>Jump on Hover</span>
          <ToggleSwitch checked={values.jump_on_hover} onChange={(checked) => onSetValue('jump_on_hover', checked)} />
          <small>Play the jump animation when the chat pet is hovered.</small>
        </label>
      </section>
    </>
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
  return (
    <section className="detail-section">
      <div className="detail-section-heading">
        <h3>Pet List</h3>
        <button className="settings-secondary-button" type="button" disabled={Boolean(busy)} onClick={onScanPets}>
          <RefreshCw size={14} />
          {busy === 'scan' ? 'Scanning...' : 'Scan Pets'}
        </button>
      </div>
      {pets.length ? (
        <div className="pet-list">
          {pets.map((pet) => (
            <PetListItem key={pet.id} pet={pet} busy={busy} onDeletePet={onDeletePet} />
          ))}
        </div>
      ) : (
        <div className="settings-empty-state compact">No pets found under <code>data/pet</code>.</div>
      )}
    </section>
  );
}

function PetListItem({ pet, busy, onDeletePet }: { pet: PetItem; busy: string; onDeletePet: (pet: PetItem) => void }) {
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
        <span>{pet.description || 'No description'}</span>
        <div className="pet-list-meta">
          <span>{pet.source}</span>
          <span className={pet.valid ? 'settings-badge success' : 'settings-badge warning'}>{pet.status}</span>
          {!pet.valid && pet.errors?.length ? <small>{pet.errors.join('; ')}</small> : null}
        </div>
      </div>
      {canDelete ? (
        <button className="settings-secondary-button danger pet-delete-button" type="button" disabled={deleting} onClick={() => onDeletePet(pet)}>
          <Trash2 size={14} />
          {deleting ? 'Deleting...' : 'Delete'}
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
    pet_scale: typeof settings.pet_scale === 'number' ? settings.pet_scale : Number(settings.pet_scale) || 1,
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
  };
}

function clampNumber(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, Math.round(value)));
}
