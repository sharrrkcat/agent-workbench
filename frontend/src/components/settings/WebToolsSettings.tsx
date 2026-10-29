import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { InputGroup, InputGroupAddon, InputGroupInput } from '@/components/ui/input-group';
import { LoadingStatus } from '@/components/ui/loading-status';
import { toolsApi } from '@/api/tools';
import type { WebToolsSettings as Settings } from '@/types/tools';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { errorText, Feedback, useResourceTask, useSettingsLeaveGuard } from './resources/ResourceUI';

export function WebToolsSettings() {
  const { t } = useTranslation('settings');
  const [settings, setSettings] = useState<Settings | null>(null);
  const [key, setKey] = useState('');
  const [maxResults, setMaxResults] = useState('10');
  const [zone, setZone] = useState<'default' | 'cn' | 'intl'>('default');
  const [language, setLanguage] = useState('');
  const [reload, setReload] = useState(0);
  const task = useResourceTask();
  const { confirm, confirmation } = useConfirmDialog();
  const { setError } = task;
  const dirty = !!key || !!settings && (maxResults !== String(settings.max_results) ||
    zone !== (settings.zone ?? 'default') || language !== (settings.language ?? ''));
  function resetOptions(value: Settings) {
    setMaxResults(String(value.max_results));
    setZone(value.zone ?? 'default');
    setLanguage(value.language ?? '');
  }
  useEffect(() => {
    let live = true;
    setError('');
    void toolsApi.getWebSettings().then((value) => {
      if (live) { setSettings(value); resetOptions(value); }
    }).catch((error) => { if (live) setError(errorText(error)); });
    return () => { live = false; };
  }, [reload, setError]);
  useSettingsLeaveGuard(useCallback(async () => {
    if (task.busy) return false;
    return !dirty || await confirm(t('resources.discardConfirm'));
  }, [dirty, task.busy, confirm, t]));

  async function save(clearKey = false) {
    const patch = clearKey ? { api_key: '' } : {
      max_results: Number(maxResults), zone: zone === 'default' ? null : zone, language: language.trim() || null,
      ...(key ? { api_key: key } : {}),
    };
    const updated = await task.run('save', () => toolsApi.patchWebSettings(patch), t('saved'));
    if (updated) {
      setSettings(updated);
      setKey('');
      if (!clearKey) resetOptions(updated);
    }
  }

  return <section className="flex min-w-0 flex-col gap-3" aria-labelledby="web-tools-settings">
    <h2 id="web-tools-settings">AnySearch</h2>
    <Feedback error={task.error} notice={task.notice} />
    {settings ? <form className="flex max-w-3xl flex-col gap-3" onSubmit={(event) => {
      event.preventDefault();
      void save();
    }}>
      <FieldGroup>
        <Field data-disabled={!!task.busy}>
          <FieldLabel htmlFor="anysearch-api-key">{t('webTools.apiKey')}</FieldLabel>
          <InputGroup>
            <InputGroupInput id="anysearch-api-key" type="password" autoComplete="new-password"
              disabled={!!task.busy} value={key} placeholder={settings.has_api_key ? t('webTools.keySet') : t('webTools.keyMissing')}
              onChange={(event) => { setKey(event.target.value); task.setNotice(''); }} />
            {settings.has_api_key ? <InputGroupAddon align="inline-end">
              <Button type="button" variant="ghost" size="sm" disabled={!!task.busy} onClick={() => void save(true)}>
                {t('webTools.clearKey')}
              </Button>
            </InputGroupAddon> : null}
          </InputGroup>
        </Field>
      </FieldGroup>
      <FieldGroup className="grid gap-4 sm:grid-cols-2">
        <Field data-disabled={!!task.busy}>
          <FieldLabel htmlFor="web-max-results">{t('webTools.maxResults')}</FieldLabel>
          <Input id="web-max-results" type="number" min={1} max={10} step={1} required disabled={!!task.busy}
            value={maxResults} onChange={(event) => { setMaxResults(event.target.value); task.setNotice(''); }} />
        </Field>
        <Field data-disabled={!!task.busy}>
          <FieldLabel htmlFor="web-search-language">{t('webTools.language')}</FieldLabel>
          <Input id="web-search-language" placeholder="en / zh-CN" disabled={!!task.busy} value={language}
            onChange={(event) => { setLanguage(event.target.value); task.setNotice(''); }} />
        </Field>
        <Field data-disabled={!!task.busy} className="sm:col-span-2">
          <FieldLabel id="web-zone-label">{t('webTools.zone')}</FieldLabel>
          <ToggleGroup aria-labelledby="web-zone-label" variant="outline" value={[zone]} disabled={!!task.busy}
            onValueChange={(values) => { if (values[0]) { setZone(values[0] as typeof zone); task.setNotice(''); } }}>
            <ToggleGroupItem value="default">{t('webTools.zones.default')}</ToggleGroupItem>
            <ToggleGroupItem value="cn">{t('webTools.zones.cn')}</ToggleGroupItem>
            <ToggleGroupItem value="intl">{t('webTools.zones.intl')}</ToggleGroupItem>
          </ToggleGroup>
        </Field>
      </FieldGroup>
      <div className="settings-form-actions">
        <Button type="submit" disabled={!!task.busy || !dirty}>{t('save')}</Button>
      </div>
    </form> : task.error ? <Button type="button" variant="outline" className="self-start" onClick={() => setReload((value) => value + 1)}>
      {t('resources.refresh')}
    </Button> : <LoadingStatus />}
    {confirmation}
  </section>;
}
