import { Switch } from '@/components/ui/switch';
import { Field, FieldLabel, FieldSet } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { Button } from '@/components/ui/button';
import { useEffect, useState } from 'react';
import { Save } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { WorldbookSettingsInput } from '../../../types/worldbook';
import { worldbookApi } from '../../../api/worldbook';

import { equalDraft, errorText, Feedback, ResourceLoading, useResourceTask } from '../resources/ResourceUI';

export function worldbookSettingsInput(value: WorldbookSettingsInput): WorldbookSettingsInput {
  return {
    worldbook_enabled: value.worldbook_enabled,
    worldbook_max_entries_per_call: value.worldbook_max_entries_per_call,
    worldbook_max_context_chars: value.worldbook_max_context_chars,
    worldbook_recursion_depth: value.worldbook_recursion_depth,
    worldbook_case_sensitive: value.worldbook_case_sensitive,
    worldbook_regex_case_insensitive: !value.worldbook_case_sensitive,
    worldbook_whole_words: value.worldbook_whole_words,
  };
}

export function WorldbookDefaults({
  onState,
}: {
  onState: (value: { dirty: boolean; busy: boolean }) => void;
}) {
  const { t } = useTranslation('worldbook');
  const [draft, setDraft] = useState<WorldbookSettingsInput | null>(null);
  const [baseline, setBaseline] = useState<WorldbookSettingsInput | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const task = useResourceTask();
  const dirty = !equalDraft(draft, baseline);
  useEffect(() => {
    onState({ dirty, busy: !!task.busy });
  }, [dirty, task.busy, onState]);
  useEffect(() => {
    let live = true;
    setError('');
    void worldbookApi
      .getWorldbookSettings()
      .then((value) => {
        if (live) {
          setDraft(worldbookSettingsInput(value));
          setBaseline(worldbookSettingsInput(value));
        }
      })
      .catch((reason) => {
        if (live) setError(errorText(reason));
      });
    return () => {
      live = false;
    };
  }, [revision]);
  if (!draft) return <ResourceLoading error={error} retry={() => setRevision((value) => value + 1)} />;
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void task.run(
          'save',
          async () => {
            const value = worldbookSettingsInput(
              await worldbookApi.updateWorldbookSettings(worldbookSettingsInput(draft)),
            );
            setDraft(value);
            setBaseline(value);
          },
          t('saved'),
        );
      }}
    >
      <Feedback {...task} />
      <FieldSet className="resource-fieldset" disabled={!!task.busy}>
        <Field orientation="horizontal">
          <Switch
            checked={draft.worldbook_enabled}
            onCheckedChange={(value) => setDraft({ ...draft, worldbook_enabled: value })}
          />
          <FieldLabel>{t('enabled')}</FieldLabel>
        </Field>
        <Field>
          <FieldLabel>{t('maximumEntries')}</FieldLabel>
          <Input
            type="number"
            min={1}
            max={200}
            step={1}
            required
            value={
              Number.isNaN(draft.worldbook_max_entries_per_call)
                ? ''
                : (draft.worldbook_max_entries_per_call ?? '')
            }
            onChange={(event) =>
              setDraft({
                ...draft,
                worldbook_max_entries_per_call:
                  event.currentTarget.value === '' ? Number.NaN : Number(event.currentTarget.value),
              })
            }
          />
        </Field>
        <Collapsible className="resource-advanced">
          <CollapsibleTrigger render={<Button type="button" variant="ghost" className="justify-start" />}>
            {t('settings:resources.advanced')}
          </CollapsibleTrigger>
          <CollapsibleContent keepMounted>
            <Field>
              <FieldLabel>{t('maxContext')}</FieldLabel>
              <Input
                type="number"
                min={1000}
                max={200000}
                step={1}
                required
                value={
                  Number.isNaN(draft.worldbook_max_context_chars)
                    ? ''
                    : (draft.worldbook_max_context_chars ?? '')
                }
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    worldbook_max_context_chars:
                      event.currentTarget.value === '' ? Number.NaN : Number(event.currentTarget.value),
                  })
                }
              />
            </Field>
            <Field>
              <FieldLabel>{t('recursionDepth')}</FieldLabel>
              <Input
                type="number"
                min={0}
                max={5}
                step={1}
                required
                value={
                  Number.isNaN(draft.worldbook_recursion_depth) ? '' : (draft.worldbook_recursion_depth ?? '')
                }
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    worldbook_recursion_depth:
                      event.currentTarget.value === '' ? Number.NaN : Number(event.currentTarget.value),
                  })
                }
              />
            </Field>
            <Field orientation="horizontal">
              <Switch
                checked={draft.worldbook_case_sensitive}
                onCheckedChange={(value) =>
                  setDraft({
                    ...draft,
                    worldbook_case_sensitive: value,
                    worldbook_regex_case_insensitive: !value,
                  })
                }
              />
              <FieldLabel>{t('caseSensitive')}</FieldLabel>
            </Field>
            <Field orientation="horizontal">
              <Switch
                checked={draft.worldbook_whole_words}
                onCheckedChange={(value) => setDraft({ ...draft, worldbook_whole_words: value })}
              />
              <FieldLabel>{t('wholeWords')}</FieldLabel>
            </Field>
          </CollapsibleContent>
        </Collapsible>
        <div className="resource-form-footer">
          <Button type="submit" disabled={!dirty} variant="default">
            <Save size={16} />
            {t('common:save')}
          </Button>
        </div>
      </FieldSet>
    </form>
  );
}
