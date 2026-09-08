import { useEffect, useState } from 'react';
import { Save } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { WorldbookSettingsInput } from '../../../types/worldbook';
import { worldbookApi } from '../../../api/worldbook';
import { ToggleSwitch } from '../../ui/ToggleSwitch';
import { equalDraft, errorText, Feedback, NumberInput, ResourceLoading, useResourceTask } from '../resources/ResourceUI';

export function worldbookSettingsInput(value: WorldbookSettingsInput): WorldbookSettingsInput {
  return { worldbook_enabled: value.worldbook_enabled, worldbook_max_entries_per_call: value.worldbook_max_entries_per_call,
    worldbook_max_context_chars: value.worldbook_max_context_chars, worldbook_recursion_depth: value.worldbook_recursion_depth,
    worldbook_case_sensitive: value.worldbook_case_sensitive, worldbook_regex_case_insensitive: !value.worldbook_case_sensitive,
    worldbook_whole_words: value.worldbook_whole_words };
}

export function WorldbookDefaults({ onState }: { onState: (value: { dirty: boolean; busy: boolean }) => void }) {
  const { t } = useTranslation('worldbook');
  const [draft, setDraft] = useState<WorldbookSettingsInput | null>(null);
  const [baseline, setBaseline] = useState<WorldbookSettingsInput | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const task = useResourceTask();
  const dirty = !equalDraft(draft, baseline);
  useEffect(() => { onState({ dirty, busy: !!task.busy }); }, [dirty, task.busy, onState]);
  useEffect(() => {
    let live = true; setError('');
    void worldbookApi.getWorldbookSettings().then((value) => { if (live) { setDraft(worldbookSettingsInput(value)); setBaseline(worldbookSettingsInput(value)); } })
      .catch((reason) => { if (live) setError(errorText(reason)); });
    return () => { live = false; };
  }, [revision]);
  if (!draft) return <ResourceLoading error={error} retry={() => setRevision((value) => value + 1)} />;
  return <form onSubmit={(event) => { event.preventDefault(); void task.run('save', async () => {
    const value = worldbookSettingsInput(await worldbookApi.updateWorldbookSettings(worldbookSettingsInput(draft)));
    setDraft(value); setBaseline(value);
  }, t('saved')); }}>
    <Feedback {...task} /><fieldset className="resource-fieldset" disabled={!!task.busy}>
      <ToggleSwitch checked={draft.worldbook_enabled} label={t('enabled')} onChange={(value) => setDraft({ ...draft, worldbook_enabled: value })} />
      <NumberInput label={t('maximumEntries')} min={1} max={200} value={draft.worldbook_max_entries_per_call} onChange={(value) => setDraft({ ...draft, worldbook_max_entries_per_call: value ?? 1 })} />
      <details className="resource-advanced"><summary>{t('settings:resources.advanced')}</summary>
        <NumberInput label={t('maxContext')} min={1000} max={200000} value={draft.worldbook_max_context_chars} onChange={(value) => setDraft({ ...draft, worldbook_max_context_chars: value ?? 1000 })} />
        <NumberInput label={t('recursionDepth')} min={0} max={5} value={draft.worldbook_recursion_depth} onChange={(value) => setDraft({ ...draft, worldbook_recursion_depth: value ?? 0 })} />
        <ToggleSwitch checked={draft.worldbook_case_sensitive} label={t('caseSensitive')} onChange={(value) => setDraft({ ...draft, worldbook_case_sensitive: value, worldbook_regex_case_insensitive: !value })} />
        <ToggleSwitch checked={draft.worldbook_whole_words} label={t('wholeWords')} onChange={(value) => setDraft({ ...draft, worldbook_whole_words: value })} />
      </details>
      <div className="resource-form-footer"><button type="submit" className="primary-button" disabled={!dirty}><Save size={16} />{t('common:save')}</button></div>
    </fieldset>
  </form>;
}
