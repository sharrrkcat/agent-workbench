import { Switch } from '@/components/ui/switch';
import { FieldGroup, Field, FieldLabel, FieldSet, FieldLegend } from '@/components/ui/field';
import { Separator } from '@/components/ui/separator';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { settingsApi } from '../../api/settings';
import type { GeneralSettings, GeneralSettingsPatch } from '../../types/settings';

import { useSettingsFeedback } from './useSettingsFeedback';
import { Feedback, ResourceLoading } from './resources/ResourceUI';
import { useCogitaStore } from '../../store/useCogitaStore';

export function GeneralPanel() {
  const [settings, setSettings] = useState<GeneralSettings | null>(null);
  const [error, setError] = useState('');
  const { run: save, message, error: saveError } = useSettingsFeedback();
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
  if (error || !settings) return <ResourceLoading error={error} />;
  return (
    <>
      <GeneralSettingsForm
        settings={settings}
        onChange={setSettings}
        onSave={(patch) =>
          save(async () => {
            const saved = await settingsApi.updateGeneralSettings(patch);
            useCogitaStore.getState().setSettings(saved);
            setSettings(saved);
          })
        }
      />
      <Feedback error={saveError} notice={message} />
    </>
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
    <section className="settings-panel settings-form">
      <FieldGroup>
        <FieldSet>
          <FieldLegend>{t('generalSections.conversation')}</FieldLegend>
          <Field orientation="horizontal">
            <Switch
              checked={settings.show_full_processing}
              onCheckedChange={(value) => patch('show_full_processing', value)}
            />
            <FieldLabel>{t('generalFields.showFullProcessing')}</FieldLabel>
          </Field>
        </FieldSet>
        <Separator />
        <FieldSet>
          <FieldLegend>{t('generalSections.titles')}</FieldLegend>
          <FieldGroup>
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
          </FieldGroup>
        </FieldSet>
        <div className="settings-form-actions">
          <Button
            type="button"
            onClick={() =>
              onSave({
                show_full_processing: settings.show_full_processing,
                auto_generate_session_titles: settings.auto_generate_session_titles,
                session_title_max_input_chars: settings.session_title_max_input_chars,
              })
            }
            variant="default"
          >
            {t('generalFields.save')}
          </Button>
        </div>
      </FieldGroup>
    </section>
  );
}
