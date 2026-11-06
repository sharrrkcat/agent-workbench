import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pencil, Plus, RefreshCw, Save, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Field, FieldLabel, FieldSet, FieldGroup } from '@/components/ui/field';
import { Textarea } from '@/components/ui/textarea';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { chatApi } from '../../api/chat';
import { usePersonasStore } from '../../store/usePersonasStore';
import type { Persona, PersonaInput } from '../../types/chat';
import { PersonaAvatar } from '../personas/ConfigurationFields';
import { IdentityAvatarField } from '../personas/IdentityAvatarField';
import { Feedback, ResourceEmpty, ResourceLoading, useResourceTask, useSettingsLeaveGuard } from './resources/ResourceUI';

type Editor = { id?: string; value: PersonaInput };
export const personaInput = (persona: Persona): PersonaInput => ({
  name: persona.name, avatar_attachment_id: persona.avatar_attachment_id, background: persona.background,
});

export function PersonasPanel() {
  const { t } = useTranslation('personas');
  const { confirm, confirmation } = useConfirmDialog();
  const personas = usePersonasStore((state) => state.personas);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [baseline, setBaseline] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [uploading, setUploading] = useState(false);
  const live = useRef(true);
  const task = useResourceTask();
  const busy = !!task.busy || uploading;
  const dirty = !!editor && JSON.stringify(editor) !== baseline;
  const leaveStatus = useRef({ busy, dirty });
  leaveStatus.current = { busy, dirty };
  const canLeave = useCallback(async () => !busy && (!dirty || await confirm(t('discardChanges'))), [busy, dirty, confirm, t]);
  useSettingsLeaveGuard(canLeave);
  const formId = useId();
  function begin(value: Editor) { setEditor(value); setBaseline(JSON.stringify(value)); }
  async function load() {
    await usePersonasStore.getState().reload(true);
    if (live.current) setLoaded(true);
  }
  useEffect(() => {
    live.current = true; void task.run('load', load);
    const unload = (event: BeforeUnloadEvent) => {
      if (leaveStatus.current.busy || leaveStatus.current.dirty) { event.preventDefault(); event.returnValue = ''; }
    };
    window.addEventListener('beforeunload', unload);
    return () => { live.current = false; window.removeEventListener('beforeunload', unload); };
  }, []);
  async function save() {
    if (!editor || uploading) return;
    await task.run('save', async () => {
      const saved = editor.id ? await chatApi.patchPersona(editor.id, editor.value) : await chatApi.createPersona(editor.value);
      usePersonasStore.getState().upsert(saved);
      if (live.current) setEditor(null);
    }, t('saved'));
  }
  const patch = (values: Partial<PersonaInput>) => setEditor((current) => current ? { ...current, value: { ...current.value, ...values } } : current);
  return <section className="resource-panel">
    <div className="resource-toolbar">
      <h2>{t('personasTitle')}</h2>
      <div className="resource-actions">
        <Button type="button" variant="ghost" size="icon" aria-label={t('refresh')} disabled={busy}
          onClick={() => void task.run('load', load)}><RefreshCw data-icon="inline-start" /></Button>
        <Button type="button" disabled={busy} onClick={() => begin({ value: { name: '', avatar_attachment_id: null, background: '' } })}>
          <Plus data-icon="inline-start" />{t('add')}
        </Button>
      </div>
    </div>
    <Feedback error={task.error} notice={task.notice} />
    {!loaded ? <ResourceLoading error={task.error} retry={() => void task.run('load', load)} /> : !personas.length
      ? <ResourceEmpty>{t('noPersonas')}</ResourceEmpty> : <div className="persona-list">
        {personas.map((persona) => <div className="persona-row" key={persona.id}>
          <PersonaAvatar name={persona.name} attachmentId={persona.avatar_attachment_id} />
          <span className="min-w-0 flex-1 truncate">{persona.name}</span>
          <div className="resource-actions">
            <Button type="button" variant="ghost" size="icon" aria-label={t('editNamed', { name: persona.name })} disabled={busy}
              onClick={() => begin({ id: persona.id, value: personaInput(persona) })}><Pencil data-icon="inline-start" /></Button>
            {!persona.is_protected ? <Button type="button" variant="ghost" size="icon" aria-label={t('deleteNamed', { name: persona.name })} disabled={busy}
              onClick={async () => {
                if (await confirm(t('deleteConfirm', { name: persona.name }), { destructive: true }))
                  void task.run('delete', async () => { await chatApi.deletePersona(persona.id); usePersonasStore.getState().remove(persona.id); });
              }}><Trash2 data-icon="inline-start" /></Button> : null}
          </div>
        </div>)}
      </div>}
    <Dialog open={!!editor} onOpenChange={(open) => { if (!open) void canLeave().then((allowed) => { if (allowed) setEditor(null); }); }}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader><DialogTitle>{editor?.id ? t('edit') : t('add')}</DialogTitle></DialogHeader>
        {editor ? <form className="settings-dialog-form" onSubmit={(event) => { event.preventDefault(); void save(); }}>
          <Feedback error={task.error} />
          <div className="settings-dialog-body"><FieldSet disabled={!!task.busy}><FieldGroup>
            <IdentityAvatarField key={editor.id ?? 'new'} name={editor.value.name} value={editor.value.avatar_attachment_id}
              disabled={!!task.busy} onChange={(id) => patch({ avatar_attachment_id: id })} onBusyChange={setUploading} onError={task.setError} />
            <Field><FieldLabel htmlFor={formId + '-name'}>{t('name')}</FieldLabel>
              <Input id={formId + '-name'} required maxLength={128} value={editor.value.name} onChange={(event) => patch({ name: event.target.value })} /></Field>
            <Field><FieldLabel htmlFor={formId + '-background'}>{t('background')}</FieldLabel>
              <Textarea id={formId + '-background'} rows={8} maxLength={100000} value={editor.value.background} onChange={(event) => patch({ background: event.target.value })} /></Field>
          </FieldGroup></FieldSet></div>
          <DialogFooter><Button type="submit" disabled={busy || !dirty}><Save data-icon="inline-start" />{t('save')}</Button></DialogFooter>
        </form> : null}
      </DialogContent>
    </Dialog>
    {confirmation}
  </section>;
}
