import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { settingsApi } from '../../api/settings';
import { ApiError } from '../../api/http';
import type { PetBubbleTexts, PetItem, PetSettings } from '../../types/settings';
import { Loading, NumberField, Panel, Toggle } from './fields';

const bubbleKeys: Array<keyof PetBubbleTexts> = [
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

export function PetSettingsPanel() {
  const { t } = useTranslation('pet');
  const [settings, setSettings] = useState<PetSettings | null>(null);
  const [pets, setPets] = useState<PetItem[]>([]);
  const [manifest, setManifest] = useState<File | null>(null);
  const [sprite, setSprite] = useState<File | null>(null);
  const [feedback, setFeedback] = useState('');
  const load = () =>
    Promise.all([settingsApi.getPetSettings(), settingsApi.listPets()]).then(([s, p]) => {
      setSettings(s.settings);
      setPets(p.pets);
    });
  useEffect(() => {
    void load();
  }, []);
  if (!settings) return <Loading />;
  const update = (patch: Partial<PetSettings>) => setSettings({ ...settings, ...patch });
  async function save(patch: Partial<PetSettings>) {
    try {
      const response = await settingsApi.updatePetSettings(patch);
      setSettings(response.settings);
      window.dispatchEvent(new Event('pet-settings-changed'));
      setFeedback(t('settings:saved'));
    } catch (error) {
      setFeedback(error instanceof ApiError ? `${error.code}: ${error.message}` : t('settings:failed'));
    }
  }
  async function importPet() {
    if (!manifest || !sprite) return;
    try {
      const response = await settingsApi.importPet(manifest, sprite);
      setPets(response.pets);
      setSettings(response.settings);
      setFeedback(t('imported'));
      window.dispatchEvent(new Event('pet-settings-changed'));
    } catch (error) {
      setFeedback(error instanceof ApiError ? `${error.code}: ${error.message}` : t('importFailed'));
    }
  }
  async function deletePet(id: string) {
    if (!window.confirm(t('deleteConfirm'))) return;
    try {
      const response = await settingsApi.deletePet(id);
      setPets(response.pets);
      setFeedback(t('deleted'));
      window.dispatchEvent(new Event('pet-settings-changed'));
    } catch (error) {
      setFeedback(error instanceof ApiError ? `${error.code}: ${error.message}` : t('deleteFailed'));
    }
  }
  return (
    <Panel title={t('title')}>
      <Toggle
        label={t('showPet')}
        checked={settings.pet_enabled}
        onChange={(value) => {
          update({ pet_enabled: value });
          void save({ pet_enabled: value });
        }}
      />
      <Toggle
        label={t('showBubble')}
        checked={settings.show_status_bubble}
        onChange={(value) => {
          update({ show_status_bubble: value });
          void save({ show_status_bubble: value });
        }}
      />
      <Toggle
        label={t('jumpOnHover')}
        checked={settings.jump_on_hover}
        onChange={(value) => {
          update({ jump_on_hover: value });
          void save({ jump_on_hover: value });
        }}
      />
      <NumberField
        label={t('scale')}
        value={settings.pet_scale}
        onChange={(value) => {
          update({ pet_scale: value });
          void save({ pet_scale: value });
        }}
      />
      <label className="settings-field">
        <span>{t('defaultPet')}</span>
        <select
          value={settings.default_pet_id}
          onChange={(event) => {
            const value = event.currentTarget.value;
            update({ default_pet_id: value });
            void save({ default_pet_id: value });
          }}
        >
          <option value="">{t('automatic')}</option>
          {pets
            .filter((item) => item.valid)
            .map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name}
              </option>
            ))}
        </select>
      </label>
      <div className="pet-import">
        <h3>{t('importPackage')}</h3>
        <label>
          pet.json{' '}
          <input
            type="file"
            accept="application/json"
            onChange={(event) => setManifest(event.target.files?.[0] || null)}
          />
        </label>
        <label>
          spritesheet.webp{' '}
          <input type="file" accept="image/webp" onChange={(event) => setSprite(event.target.files?.[0] || null)} />
        </label>
        <button
          className="secondary-button"
          type="button"
          disabled={!manifest || !sprite}
          onClick={() => void importPet()}
        >
          {t('import')}
        </button>
      </div>
      <div className="settings-list">
        {pets.map((item) => (
          <div className="settings-list-row" key={item.id}>
            <span>
              {item.display_name}
              <small>
                {t('packageStates.' + (item.valid ? 'valid' : item.status), { defaultValue: item.status || '' })}
              </small>
            </span>
            {item.can_delete !== false ? (
              <button type="button" onClick={() => void deletePet(item.id)}>
                {t('common:delete')}
              </button>
            ) : null}
          </div>
        ))}
      </div>
      <details className="bubble-editor">
        <summary>{t('bubbleText')}</summary>
        {bubbleKeys.map((key) => (
          <label className="settings-field" key={key}>
            <span>{t('bubbleLabels.' + key)}</span>
            <input
              value={settings.bubble_texts[key]}
              onChange={(event) =>
                update({ bubble_texts: { ...settings.bubble_texts, [key]: event.currentTarget.value } })
              }
              onBlur={() => void save({ bubble_texts: settings.bubble_texts })}
            />
          </label>
        ))}
      </details>
      {feedback ? <p className="settings-feedback">{feedback}</p> : null}
    </Panel>
  );
}
