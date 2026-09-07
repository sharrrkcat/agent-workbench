import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { worldbookApi } from '../../api/worldbook';
import type { Worldbook, WorldbookSettings } from '../../types/worldbook';
import { Loading, NumberField, Panel, Toggle } from './fields';
import type { SettingsTask } from './useSettingsFeedback';

export function WorldbookPanel({ save }: { save: SettingsTask }) {
  const { t } = useTranslation('worldbook');
  const [settings, setSettings] = useState<WorldbookSettings | null>(null);
  const [items, setItems] = useState<Worldbook[]>([]);
  const [name, setName] = useState('');
  const reload = () =>
    Promise.all([worldbookApi.getWorldbookSettings(), worldbookApi.listWorldbooks()]).then(([s, w]) => {
      setSettings(s);
      setItems(w);
    });
  useEffect(() => {
    void reload();
  }, []);
  if (!settings) return <Loading />;
  return (
    <Panel title={t('title')}>
      <Toggle
        label={t('enabled')}
        checked={settings.worldbook_enabled}
        onChange={(value) => setSettings({ ...settings, worldbook_enabled: value })}
      />
      <NumberField
        label={t('maximumEntries')}
        value={settings.worldbook_max_entries_per_call}
        onChange={(value) => setSettings({ ...settings, worldbook_max_entries_per_call: value })}
      />
      <button
        className="primary-button"
        type="button"
        onClick={() => save(() => worldbookApi.updateWorldbookSettings(settings).then(() => undefined))}
      >
        {t('save')}
      </button>
      <h3>{t('worldbooks')}</h3>
      <div className="settings-list">
        {items.map((item) => (
          <div className="settings-list-row" key={item.id}>
            <span>
              {item.name}
              <small>{t('entryCount', { count: item.entry_count || 0 })}</small>
            </span>
            <button
              type="button"
              onClick={() => save(() => worldbookApi.deleteWorldbook(item.id).then(() => reload()))}
            >
              {t('common:delete')}
            </button>
          </div>
        ))}
      </div>
      <div className="inline-form">
        <input placeholder={t('worldbookName')} value={name} onChange={(event) => setName(event.currentTarget.value)} />
        <button
          className="secondary-button"
          type="button"
          disabled={!name.trim()}
          onClick={() =>
            save(() =>
              worldbookApi.createWorldbook({ name }).then(() => {
                setName('');
                return reload();
              }),
            )
          }
        >
          {t('addWorldbook')}
        </button>
      </div>
    </Panel>
  );
}
