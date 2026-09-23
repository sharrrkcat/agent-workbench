import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Input } from '@/components/ui/input';
import { Field, FieldLabel, FieldSet } from '@/components/ui/field';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { useEffect, useState } from 'react';
import { ArrowLeft, Save, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { Worldbook, WorldbookInput } from '../../../types/worldbook';
import { worldbookApi } from '../../../api/worldbook';

import { equalDraft, errorText, Feedback, ResourceLoading, useResourceTask } from '../resources/ResourceUI';
import { WorldbookEntries } from './WorldbookEntries';
import { WorldbookMatch } from './WorldbookMatch';

export function WorldbookDetail({
  id,
  onBack,
  onSaved,
  onDeleted,
  onState,
}: {
  id: string;
  onBack: () => void;
  onSaved: (book: Worldbook, created: boolean) => void;
  onDeleted: () => void;
  onState: (value: { dirty: boolean; busy: boolean }) => void;
}) {
  const { confirm, confirmation } = useConfirmDialog();
  const { t } = useTranslation('worldbook');
  const empty: WorldbookInput = { name: '', description: '', enabled: true };
  const [baseline, setBaseline] = useState(empty);
  const [draft, setDraft] = useState(empty);
  const [book, setBook] = useState<Worldbook | null>(null);
  const [tab, setTab] = useState<'config' | 'entries' | 'match'>(id === 'new' ? 'config' : 'entries');
  const [loading, setLoading] = useState(id !== 'new');
  const [loadError, setLoadError] = useState('');
  const [revision, setRevision] = useState(0);
  const [entryState, setEntryState] = useState({ dirty: false, busy: false });
  const task = useResourceTask();
  const dirty = !equalDraft(draft, baseline);
  useEffect(() => {
    onState({ dirty: dirty || entryState.dirty, busy: !!task.busy || entryState.busy });
  }, [dirty, entryState, task.busy, onState]);
  useEffect(() => {
    if (id === 'new') return;
    let live = true;
    setLoading(true);
    setLoadError('');
    void worldbookApi
      .getWorldbook(id)
      .then((value) => {
        if (!live) return;
        const input = { name: value.name, description: value.description, enabled: value.enabled };
        setBook(value);
        setBaseline(input);
        setDraft(input);
        setLoading(false);
      })
      .catch((reason) => {
        if (live) {
          setLoadError(errorText(reason));
          setLoading(false);
        }
      });
    return () => {
      live = false;
    };
  }, [id, revision]);
  const locked = !!task.busy || entryState.busy;
  if (loading || loadError)
    return (
      <>
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={t('common:back')}
                onClick={onBack}
              />
            }
          >
            <ArrowLeft size={18} />
          </TooltipTrigger>
          <TooltipContent>{t('common:back')}</TooltipContent>
        </Tooltip>
        <ResourceLoading error={loadError} retry={() => setRevision((value) => value + 1)} />
      </>
    );
  return (
    <Tabs value={tab} onValueChange={setTab}>
      <div className="resource-heading">
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={t('common:back')}
                disabled={locked}
                onClick={onBack}
              />
            }
          >
            <ArrowLeft size={18} />
          </TooltipTrigger>
          <TooltipContent>{t('common:back')}</TooltipContent>
        </Tooltip>
        <h2>{book?.name || t('newWorldbook')}</h2>
        {book ? (
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  type="button"
                  variant="destructive"
                  size="icon"
                  aria-label={t('common:delete')}
                  disabled={locked}
                  onClick={async () => {
                    if (await confirm(t('deleteBookConfirm', { name: book.name }), { destructive: true }))
                      void task.run('delete', async () => {
                        await worldbookApi.deleteWorldbook(book.id);
                        onDeleted();
                      });
                  }}
                />
              }
            >
              <Trash2 size={16} />
            </TooltipTrigger>
            <TooltipContent>{t('common:delete')}</TooltipContent>
          </Tooltip>
        ) : null}
      </div>
      <TabsList aria-label={t('settings:resources.sections')}>
        {[
          { id: 'config', label: t('config') },
          { id: 'entries', label: t('entries'), disabled: !book },
          { id: 'match', label: t('matchTest'), disabled: !book },
        ].map((item) => (
          <TabsTrigger key={item.id} value={item.id} disabled={'disabled' in item && !!item.disabled}>
            {item.label}
          </TabsTrigger>
        ))}
      </TabsList>
      <Feedback {...task} />
      <TabsContent value="config" keepMounted hidden={tab !== 'config'}>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void task.run(
              'save',
              async () => {
                const saved = book
                  ? await worldbookApi.patchWorldbook(book.id, draft)
                  : await worldbookApi.createWorldbook(draft);
                setBook(saved);
                setDraft({ name: saved.name, description: saved.description, enabled: saved.enabled });
                setBaseline({ name: saved.name, description: saved.description, enabled: saved.enabled });
                onSaved(saved, !book);
              },
              t('saved'),
            );
          }}
        >
          <FieldSet className="resource-fieldset" disabled={locked}>
            <Field>
              <FieldLabel>{t('name')}</FieldLabel>
              <Input
                required
                value={draft.name}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              />
            </Field>
            <Field>
              <FieldLabel>{t('description')}</FieldLabel>
              <Textarea
                rows={4}
                value={draft.description}
                onChange={(event) => setDraft({ ...draft, description: event.target.value })}
              ></Textarea>
            </Field>
            <Field orientation="horizontal">
              <Switch
                checked={draft.enabled ?? true}
                onCheckedChange={(enabled) => setDraft({ ...draft, enabled })}
              />
              <FieldLabel>{t('bookEnabled')}</FieldLabel>
            </Field>
            <div className="resource-form-footer">
              <Button type="submit" disabled={!draft.name.trim() || (!!book && !dirty)} variant="default">
                <Save size={16} />
                {t('common:save')}
              </Button>
            </div>
          </FieldSet>
        </form>
      </TabsContent>
      {book ? (
        <>
          <TabsContent value="entries" keepMounted hidden={tab !== 'entries'}>
            <WorldbookEntries
              bookId={book.id}
              onState={setEntryState}
              onCount={(count) => onSaved({ ...book, entry_count: count }, false)}
            />
          </TabsContent>
          <TabsContent value="match" keepMounted hidden={tab !== 'match'}>
            <WorldbookMatch bookId={book.id} />
          </TabsContent>
        </>
      ) : null}
      {confirmation}
    </Tabs>
  );
}
