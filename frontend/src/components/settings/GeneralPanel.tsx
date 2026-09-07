import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { settingsApi } from '../../api/settings';
import type { GeneralSettings, GeneralSettingsPatch } from '../../types/settings';
import { Loading, NumberField, Panel, TextArea, Toggle } from './fields';
import type { SettingsTask } from './useSettingsFeedback';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';

export function GeneralPanel({ save }: { save: SettingsTask }) {
  const [settings, setSettings] = useState<GeneralSettings | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let cancelled = false;
    void settingsApi
      .getGeneralSettings()
      .then((value) => {
        if (!cancelled) setSettings(value);
      })
      .catch((reason) => {
        if (!cancelled) setError(String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, []);
  if (error)
    return (
      <p role="alert" className="error-text">
        {error}
      </p>
    );
  if (!settings) return <Loading />;
  return (
    <GeneralSettingsForm
      settings={settings}
      onChange={setSettings}
      onSave={(patch) => save(async () => {
        const saved = await settingsApi.updateGeneralSettings(patch);
        useWorkbenchStore.getState().setSettings(saved);
        setSettings(saved);
      })}
    />
  );
}

export function GeneralSettingsForm({
  settings,
  onChange,
  onSave,
}: {
  settings: GeneralSettings;
  onChange: (settings: GeneralSettings) => void;
  onSave: (patch: GeneralSettingsPatch) => void;
}) {
  const { t } = useTranslation('settings');
  function patch<K extends keyof GeneralSettings>(key: K, value: GeneralSettings[K]) {
    onChange({ ...settings, [key]: value });
  }
  return (
    <Panel title={t('general')}>
      <Toggle
        label={t('generalFields.showFullProcessing')}
        checked={settings.show_full_processing}
        onChange={(value) => patch('show_full_processing', value)}
      />
      <Toggle
        label={t('generalFields.memoryEnabled')}
        checked={settings.core_memory_enabled}
        onChange={(value) => patch('core_memory_enabled', value)}
      />
      <TextArea
        label={t('generalFields.memoryContent')}
        value={settings.core_memory_content}
        onChange={(value) => patch('core_memory_content', value)}
      />
      <Toggle
        label={t('generalFields.titlesEnabled')}
        checked={settings.auto_generate_session_titles}
        onChange={(value) => patch('auto_generate_session_titles', value)}
      />
      <NumberField
        label={t('generalFields.titleLimit')}
        value={settings.session_title_max_input_chars}
        onChange={(value) => patch('session_title_max_input_chars', value)}
      />
      <TextArea
        label={t('generalFields.groupInstruction')}
        value={settings.group_transcript_system_instruction || ''}
        onChange={(value) => patch('group_transcript_system_instruction', value || null)}
      />
      <button
        className="primary-button"
        type="button"
        onClick={() =>
          onSave({
            show_full_processing: settings.show_full_processing,
            core_memory_enabled: settings.core_memory_enabled,
            core_memory_content: settings.core_memory_content,
            auto_generate_session_titles: settings.auto_generate_session_titles,
            session_title_max_input_chars: settings.session_title_max_input_chars,
            group_transcript_system_instruction: settings.group_transcript_system_instruction,
          })
        }
      >
        {t('generalFields.save')}
      </button>
    </Panel>
  );
}
