import { useCallback, useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Save } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Field, FieldGroup, FieldLabel, FieldSet } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { memoriesApi } from '../../api/memories';
import { useCharactersStore } from '../../store/useCharactersStore';
import { usePersonasStore } from '../../store/usePersonasStore';
import type { MemoryCreate, MemoryEntry } from '../../types/memory';
import { MemorySelect } from './MemoryFields';
import { Feedback, errorText, useSettingsLeaveGuard } from '../settings/resources/ResourceUI';

export function MemoryEditor({ entry, initial, onClose, onSaved }: {
  entry?: MemoryEntry; initial: MemoryCreate; onClose: () => void; onSaved: () => void;
}) {
  const { t } = useTranslation('memory'); const id = useId();
  const { confirm, confirmation } = useConfirmDialog();
  const [draft, setDraft] = useState(initial);
  const [status, setStatus] = useState<'active' | 'needs_review'>(entry?.status === 'needs_review' ? 'needs_review' : 'active');
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const characters = useCharactersStore((s) => s.characters).filter((c) => c.kind === 'normal');
  const personas = usePersonasStore((s) => s.personas);
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial) || (entry && status !== entry.status);
  useSettingsLeaveGuard(useCallback(async () => !busy && (!dirty || await confirm(t('personas:discardChanges'))), [busy, dirty, confirm, t]));
  useEffect(() => {
    if (!dirty && !busy) return;
    const preventUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', preventUnload);
    return () => window.removeEventListener('beforeunload', preventUnload);
  }, [dirty, busy]);
  useEffect(() => {
    let live = true;
    void Promise.all([useCharactersStore.getState().reload(), usePersonasStore.getState().reload()])
      .catch((reason) => { if (live) setError(errorText(reason)); });
    return () => { live = false; };
  }, []);
  async function close() { if (!busy && (!dirty || await confirm(t('personas:discardChanges')))) onClose(); }
  async function save() {
    setBusy(true); setError('');
    try {
      if (entry) await memoriesApi.edit(entry.id, { expected_revision: entry.revision, summary: draft.summary, body: draft.body, pinned: draft.pinned, status });
      else await memoriesApi.create(draft);
      onSaved(); onClose();
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }
  const options = (values: { id: string; name: string }[], selected: string) => [
    ...values.map((v) => ({ value: v.id, label: v.name })),
    ...(!values.some((v) => v.id === selected) && selected ? [{ value: selected, label: t('deletedSource') }] : []),
  ];
  return <Dialog open onOpenChange={(open) => { if (!open) void close(); }}><DialogContent className="sm:max-w-3xl">
    <DialogHeader><DialogTitle>{t(entry ? 'edit' : 'add')}</DialogTitle></DialogHeader>
    <form className="settings-dialog-form" onSubmit={(event) => { event.preventDefault(); event.stopPropagation(); void save(); }}>
      <div className="settings-dialog-body"><Feedback error={error} /><FieldSet disabled={busy}><FieldGroup>
        <div className="grid gap-4 sm:grid-cols-2">
          <MemorySelect label={t('character')} value={draft.character_id} disabled={!!entry || !!draft.session_id} options={options(characters, draft.character_id)}
            onChange={(character_id) => setDraft({ ...draft, character_id })} />
          <MemorySelect label={t('persona')} value={draft.persona_id} disabled={!!entry || !!draft.session_id} options={options(personas, draft.persona_id)}
            onChange={(persona_id) => setDraft({ ...draft, persona_id })} />
        </div>
        {!entry && !draft.session_id ? <MemorySelect label={t('pool')} value={draft.pool}
          options={[{ value: 'character', label: t('characterPool') }, { value: 'general', label: t('general') }]}
          onChange={(pool) => setDraft({ ...draft, pool: pool as MemoryCreate['pool'] })} /> : null}
        <Field><FieldLabel htmlFor={id + '-summary'}>{t('summary')}</FieldLabel><Input id={id + '-summary'} required maxLength={160}
          value={draft.summary} onChange={(e) => setDraft({ ...draft, summary: e.target.value })} /></Field>
        <Field><FieldLabel htmlFor={id + '-body'}>{t('body')}</FieldLabel><Textarea id={id + '-body'} required rows={7} maxLength={2000}
          value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} /></Field>
        <Field orientation="horizontal"><Switch id={id + '-pin'} checked={draft.pinned} onCheckedChange={(pinned) => setDraft({ ...draft, pinned })} />
          <FieldLabel htmlFor={id + '-pin'}>{t('pinned')}</FieldLabel></Field>
        {entry ? <MemorySelect label={t('status')} value={status} options={[{ value: 'active', label: t('active') }, { value: 'needs_review', label: t('needs_review') }]}
          onChange={(value) => setStatus(value as typeof status)} /> : null}
      </FieldGroup></FieldSet></div>
      <DialogFooter><Button type="button" variant="outline" onClick={() => void close()} disabled={busy}>{t('cancel')}</Button>
        <Button type="submit" disabled={busy || !draft.character_id || !draft.persona_id}><Save data-icon="inline-start" />{t('save')}</Button></DialogFooter>
    </form>{confirmation}
  </DialogContent></Dialog>;
}
