import { useEffect, useState } from 'react';
import { ArrowLeft, Save, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { Worldbook, WorldbookInput } from '../../../types/worldbook';
import { worldbookApi } from '../../../api/worldbook';
import { ToggleSwitch } from '../../ui/ToggleSwitch';
import { equalDraft, errorText, Feedback, Field, ResourceIcon, ResourceLoading, ResourceTabs, useResourceTask } from '../resources/ResourceUI';
import { WorldbookEntries } from './WorldbookEntries';
import { WorldbookMatch } from './WorldbookMatch';

export function WorldbookDetail({ id, onBack, onSaved, onDeleted, onState }: {
  id: string; onBack: () => void; onSaved: (book: Worldbook, created: boolean) => void;
  onDeleted: () => void; onState: (value: { dirty: boolean; busy: boolean }) => void;
}) {
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
  useEffect(() => { onState({ dirty: dirty || entryState.dirty, busy: !!task.busy || entryState.busy }); }, [dirty, entryState, task.busy, onState]);
  useEffect(() => {
    if (id === 'new') return;
    let live = true; setLoading(true); setLoadError('');
    void worldbookApi.getWorldbook(id).then((value) => {
      if (!live) return;
      const input = { name: value.name, description: value.description, enabled: value.enabled };
      setBook(value); setBaseline(input); setDraft(input); setLoading(false);
    }).catch((reason) => { if (live) { setLoadError(errorText(reason)); setLoading(false); } });
    return () => { live = false; };
  }, [id, revision]);
  const locked = !!task.busy || entryState.busy;
  if (loading || loadError) return <><ResourceIcon label={t('common:back')} onClick={onBack}><ArrowLeft size={18} /></ResourceIcon><ResourceLoading error={loadError} retry={() => setRevision((value) => value + 1)} /></>;
  return <>
    <div className="resource-heading"><ResourceIcon label={t('common:back')} disabled={locked} onClick={onBack}><ArrowLeft size={18} /></ResourceIcon>
      <h2>{book?.name || t('newWorldbook')}</h2>
      {book ? <ResourceIcon label={t('common:delete')} disabled={locked} danger onClick={() => {
        if (window.confirm(t('deleteBookConfirm', { name: book.name }))) void task.run('delete', async () => { await worldbookApi.deleteWorldbook(book.id); onDeleted(); });
      }}><Trash2 size={16} /></ResourceIcon> : null}
    </div>
    <ResourceTabs value={tab} onChange={setTab} tabs={[{ id: 'config', label: t('config') }, { id: 'entries', label: t('entries'), disabled: !book }, { id: 'match', label: t('matchTest'), disabled: !book }]} />
    <Feedback {...task} />
    <div hidden={tab !== 'config'}><form onSubmit={(event) => {
      event.preventDefault(); void task.run('save', async () => {
        const saved = book ? await worldbookApi.patchWorldbook(book.id, draft) : await worldbookApi.createWorldbook(draft);
        setBook(saved); setDraft({ name: saved.name, description: saved.description, enabled: saved.enabled });
        setBaseline({ name: saved.name, description: saved.description, enabled: saved.enabled }); onSaved(saved, !book);
      }, t('saved'));
    }}><fieldset className="resource-fieldset" disabled={locked}>
      <Field label={t('name')}><input required value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></Field>
      <Field label={t('description')}><textarea rows={4} value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></Field>
      <ToggleSwitch checked={draft.enabled ?? true} label={t('bookEnabled')} onChange={(enabled) => setDraft({ ...draft, enabled })} />
      <div className="resource-form-footer"><button type="submit" className="primary-button" disabled={!draft.name.trim() || (!!book && !dirty)}><Save size={16} />{t('common:save')}</button></div>
    </fieldset></form></div>
    {book ? <><div hidden={tab !== 'entries'}><WorldbookEntries bookId={book.id} onState={setEntryState} onCount={(count) => onSaved({ ...book, entry_count: count }, false)} /></div>
      <div hidden={tab !== 'match'}><WorldbookMatch bookId={book.id} /></div></> : null}
  </>;
}
