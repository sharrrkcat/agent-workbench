import { Switch } from '@/components/ui/switch';
import { FieldGroup, Field, FieldLabel } from '@/components/ui/field';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { settingsApi } from '../../api/settings';
import type { GeneralSettings, GeneralSettingsPatch } from '../../types/settings';

import type { SettingsTask } from './useSettingsFeedback';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';

export function GeneralPanel({ save }: { save: SettingsTask }) {
  const { t } = useTranslation('common');
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
  if (!settings) return <p role="status">{t('common:loading')}</p>;
  return (
    <GeneralSettingsForm
      settings={settings}
      onChange={setSettings}
      onSave={(patch) =>
        save(async () => {
          const saved = await settingsApi.updateGeneralSettings(patch);
          useWorkbenchStore.getState().setSettings(saved);
          setSettings(saved);
        })
      }
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
    <section className="settings-panel">
      <h2>{t('general')}</h2>
      <FieldGroup>
        <Field orientation="horizontal">
          <Switch
            checked={settings.show_full_processing}
            onCheckedChange={(value) => patch('show_full_processing', value)}
          />
          <FieldLabel>{t('generalFields.showFullProcessing')}</FieldLabel>
        </Field>
        <Field orientation="horizontal">
          <Switch
            checked={settings.core_memory_enabled}
            onCheckedChange={(value) => patch('core_memory_enabled', value)}
          />
          <FieldLabel>{t('generalFields.memoryEnabled')}</FieldLabel>
        </Field>
        <Field>
          <FieldLabel>{t('generalFields.memoryContent')}</FieldLabel>
          <Textarea
            rows={4}
            value={settings.core_memory_content}
            onChange={(event) => patch('core_memory_content', event.currentTarget.value)}
          />
        </Field>
        <Field orientation="horizontal">
          <Switch
            checked={settings.auto_generate_session_titles}
            onCheckedChange={(value) => patch('auto_generate_session_titles', value)}
          />
          <FieldLabel>{t('generalFields.titlesEnabled')}</FieldLabel>
        </Field>
        <Field>
          <FieldLabel>{t('generalFields.titleLimit')}</FieldLabel>
          <Input
            type="number"
            step={1}
            value={
              Number.isNaN(settings.session_title_max_input_chars)
                ? ''
                : (settings.session_title_max_input_chars ?? '')
            }
            onChange={(event) =>
              patch(
                'session_title_max_input_chars',
                event.currentTarget.value === '' ? 0 : Number(event.currentTarget.value),
              )
            }
          />
        </Field>
        <Field>
          <FieldLabel>{t('generalFields.groupInstruction')}</FieldLabel>
          <Textarea
            rows={4}
            value={settings.group_transcript_system_instruction || ''}
            onChange={(event) =>
              patch('group_transcript_system_instruction', event.currentTarget.value || null)
            }
          />
        </Field>
        <Button
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
          variant="default"
        >
          {t('generalFields.save')}
        </Button>
      </FieldGroup>
    </section>
  );
}
