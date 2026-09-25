import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Input } from '@/components/ui/input';
import { Field, FieldLabel, FieldSet, FieldGroup } from '@/components/ui/field';
import { Textarea } from '@/components/ui/textarea';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Pencil, Plus, RefreshCw, Save, Trash2, Upload, X } from 'lucide-react';
import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { knowledgeApi } from '../../api/knowledge';
import { worldbookApi } from '../../api/worldbook';
import { chatApi } from '../../api/chat';
import { usePersonasStore } from '../../store/usePersonasStore';
import { useCogitaStore } from '../../store/useCogitaStore';
import type { Persona, PersonaCollection, PersonaInput } from '../../types/chat';
import { BindingsField, PersonaAvatar } from '../personas/ConfigurationFields';
import { Feedback, ResourceEmpty, ResourceLoading, useResourceTask, useSettingsLeaveGuard } from './resources/ResourceUI';

type Editor = { id?: string; value: PersonaInput; bindings: string[] };
type Resource = { id: string; name: string; enabled: boolean };
type ResourceKind = 'knowledge' | 'worldbook';
const personaInput = (persona: Persona): PersonaInput => ({
  name: persona.name, avatar_attachment_id: persona.avatar_attachment_id, system_prompt: persona.system_prompt,
});

export function PersonasPanel({ collection }: { collection: PersonaCollection }) {
  const { confirm, confirmation } = useConfirmDialog();
  const { t } = useTranslation('personas');
  const allPersonas = usePersonasStore((s) => s.personas);
  const personas = allPersonas.filter((p) => p.collection === collection);
  const singleton = collection === 'user';
  const kind: ResourceKind = singleton || collection === 'agent' ? 'knowledge' : 'worldbook';
  const [editor, setEditor] = useState<Editor | null>(null);
  const [baseline, setBaseline] = useState('');
  const [resources, setResources] = useState<Resource[]>([]);
  const [loaded, setLoaded] = useState(false);
  const temporaryAvatars = useRef(new Set<string>());
  const live = useRef(true);
  const task = useResourceTask();
  const busy = !!task.busy;
  const dirty = !!editor && JSON.stringify(editor) !== baseline;
  useSettingsLeaveGuard(useCallback(async () => !busy && (!dirty || await confirm(t('discardChanges'))), [busy, dirty, confirm, t]));

  function beginEdit(value: Editor) {
    setEditor(value);
    setBaseline(JSON.stringify(value));
  }
  async function bindingIds(id: string) {
    return kind === 'knowledge'
      ? (await chatApi.getPersonaKnowledge(id)).knowledge_base_ids
      : (await chatApi.getPersonaWorldbooks(id)).worldbook_ids;
  }
  async function load() {
    const [, available] = await Promise.all([
      usePersonasStore.getState().reload(),
      kind === 'knowledge' ? knowledgeApi.listKnowledgeBases() : worldbookApi.listWorldbooks(),
    ]);
    if (!live.current) return;
    setResources(available);
    if (singleton) {
      const persona = usePersonasStore.getState().personas.find((p) => p.collection === 'user');
      if (!persona) throw new Error(t('unavailable'));
      const bindings = await bindingIds(persona.id);
      if (!live.current) return;
      beginEdit({ id: persona.id, value: personaInput(persona), bindings });
    }
    setLoaded(true);
  }
  async function cleanupUploads() {
    const pending = [...temporaryAvatars.current];
    temporaryAvatars.current.clear();
    await Promise.allSettled(pending.map((id) => chatApi.deleteAttachment(id)));
  }
  useEffect(() => {
    live.current = true;
    void task.run('load', load);
    return () => { live.current = false; void cleanupUploads(); };
  }, []);

  async function edit(persona: Persona) {
    await task.run('edit', async () => {
      const bindings = await bindingIds(persona.id);
      if (live.current) beginEdit({ id: persona.id, value: personaInput(persona), bindings });
    });
  }
  function close() {
    if (busy) return;
    setEditor(null);
    void cleanupUploads();
  }
  async function save() {
    if (!editor) return;
    await task.run('save', async () => {
      let saved: Persona;
      if (editor.id) saved = await chatApi.patchPersona(editor.id, editor.value);
      else if (collection !== 'user') saved = await chatApi.createPersona({ ...editor.value, collection });
      else return;
      const next = { ...editor, id: saved.id, value: personaInput(saved) };
      setEditor(next);
      if (saved.avatar_attachment_id) temporaryAvatars.current.delete(saved.avatar_attachment_id);
      if (kind === 'knowledge') await chatApi.patchPersonaKnowledge(saved.id, editor.bindings);
      else await chatApi.patchPersonaWorldbooks(saved.id, editor.bindings);
      await usePersonasStore.getState().reload();
      await useCogitaStore.getState().reloadSessions();
      await cleanupUploads();
      if (singleton) beginEdit(next);
      else setEditor(null);
    }, t('saved'));
  }
  async function chooseAvatar(file: File) {
    await task.run('avatar', async () => {
      const result = await chatApi.uploadAttachment(file);
      if (!result.uri) throw new Error(t('unavailable'));
      const attachmentId = new URL(result.uri).pathname.slice(1);
      if (!live.current) { await chatApi.deleteAttachment(attachmentId); return; }
      temporaryAvatars.current.add(attachmentId);
      setEditor((current) => current ? { ...current, value: { ...current.value, avatar_attachment_id: attachmentId } } : null);
    });
  }
  const form = editor ? (
    <PersonaEditor key={editor.id || 'new'} editor={editor} kind={kind} resources={resources} busy={busy}
      inline={singleton} error={task.error} onChange={setEditor} onSave={() => void save()} onAvatar={(file) => void chooseAvatar(file)} />
  ) : null;
  return (
    <section className="settings-panel personas-panel" data-persona-collection={collection}>
      <div className="model-heading">
        <h2>{t('collections.' + collection)}</h2>
        <div className="model-actions">
          <Tooltip><TooltipTrigger render={
            <Button type="button" variant="ghost" size="icon" aria-label={t('refresh')} disabled={busy} onClick={async () => {
              if (!dirty || await confirm(t('discardChanges'))) {
                await cleanupUploads();
                void task.run('load', load);
              }
            }} />
          }><RefreshCw data-icon="inline-start" /></TooltipTrigger><TooltipContent>{t('refresh')}</TooltipContent></Tooltip>
          {!singleton ? <Button type="button" variant="outline" disabled={busy} onClick={() => beginEdit({
            value: { name: '', avatar_attachment_id: null, system_prompt: '' }, bindings: [],
          })}><Plus data-icon="inline-start" />{t('add')}</Button> : null}
        </div>
      </div>
      {singleton || !editor ? <Feedback error={task.error} notice={task.notice} /> : null}
      {!loaded ? <ResourceLoading /> : singleton ? form : (
        <div className="persona-list">
          {!personas.length ? <ResourceEmpty>{t('emptyPersonas')}</ResourceEmpty> : null}
          {personas.map((persona) => (
            <div className="persona-row" key={persona.id}>
              <PersonaAvatar name={persona.name} attachmentId={persona.avatar_attachment_id} />
              <div className="persona-identity"><strong>{persona.name}</strong></div>
              <div className="model-actions">
                <Tooltip><TooltipTrigger render={
                  <Button type="button" variant="ghost" size="icon" aria-label={t('editNamed', { name: persona.name })}
                    disabled={busy} onClick={() => void edit(persona)} />
                }><Pencil data-icon="inline-start" /></TooltipTrigger><TooltipContent>{t('editNamed', { name: persona.name })}</TooltipContent></Tooltip>
                {!persona.is_protected ? <Tooltip><TooltipTrigger render={
                  <Button type="button" variant="ghost" size="icon" aria-label={t('deleteNamed', { name: persona.name })}
                    disabled={busy} onClick={async () => {
                      if (await confirm(t('deleteConfirm', { name: persona.name }), { destructive: true }))
                        void task.run('delete', async () => { await chatApi.deletePersona(persona.id); await usePersonasStore.getState().reload(); });
                    }} />
                }><Trash2 data-icon="inline-start" /></TooltipTrigger><TooltipContent>{t('deleteNamed', { name: persona.name })}</TooltipContent></Tooltip> : null}
              </div>
            </div>
          ))}
        </div>
      )}
      {!singleton ? <Dialog open={!!editor} onOpenChange={(open) => { if (!open) close(); }}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader><DialogTitle>{editor?.id ? t('edit') : t('add')}</DialogTitle></DialogHeader>
          {form}
        </DialogContent>
      </Dialog> : null}
      {confirmation}
    </section>
  );
}

function PersonaEditor({ editor, kind, resources, busy, inline, error, onChange, onSave, onAvatar }: {
  editor: Editor;
  kind: ResourceKind;
  resources: Resource[];
  busy: boolean;
  inline: boolean;
  error: string;
  onChange: (value: Editor) => void;
  onSave: () => void;
  onAvatar: (file: File) => void;
}) {
  const { t } = useTranslation('personas');
  const [tab, setTab] = useState<'identity' | ResourceKind>('identity');
  const formId = useId();
  const upload = useRef<HTMLInputElement>(null);
  const patch = (values: Partial<PersonaInput>) => onChange({ ...editor, value: { ...editor.value, ...values } });
  const saveButton = <Button type="submit" disabled={busy}><Save data-icon="inline-start" />{t('save')}</Button>;
  return (
    <Tabs value={tab} onValueChange={setTab} render={
      <form className={inline ? 'settings-form' : 'settings-dialog-form'}
        onInvalidCapture={() => setTab('identity')}
        onSubmit={(event) => { event.preventDefault(); onSave(); }} />
    }>
      {!inline ? <Feedback error={error} /> : null}
      <TabsList aria-label={t('editorSections')}>
        <TabsTrigger value="identity">{t('identity')}</TabsTrigger>
        <TabsTrigger value={kind}>{t(kind)}</TabsTrigger>
      </TabsList>
      <div className={inline ? 'py-4' : 'settings-dialog-body'}>
        <FieldSet disabled={busy} className="model-form">
          <TabsContent value="identity">
            <FieldGroup>
              <div className="persona-avatar-editor">
                <PersonaAvatar name={editor.value.name} attachmentId={editor.value.avatar_attachment_id} />
                <input ref={upload} type="file" hidden accept="image/png,image/jpeg,image/webp,image/gif" onChange={(event) => {
                  const file = event.currentTarget.files?.[0]; event.currentTarget.value = ''; if (file) onAvatar(file);
                }} />
                <Tooltip><TooltipTrigger render={
                  <Button type="button" variant="ghost" size="icon" aria-label={t('uploadAvatar')} onClick={() => upload.current?.click()} />
                }><Upload data-icon="inline-start" /></TooltipTrigger><TooltipContent>{t('uploadAvatar')}</TooltipContent></Tooltip>
                <Tooltip><TooltipTrigger render={
                  <Button type="button" variant="ghost" size="icon" aria-label={t('removeAvatar')} disabled={!editor.value.avatar_attachment_id}
                    onClick={() => patch({ avatar_attachment_id: null })} />
                }><X data-icon="inline-start" /></TooltipTrigger><TooltipContent>{t('removeAvatar')}</TooltipContent></Tooltip>
              </div>
              <Field>
                <FieldLabel htmlFor={formId + '-name'}>{t('name')}</FieldLabel>
                <Input id={formId + '-name'} required maxLength={128} value={editor.value.name} onChange={(event) => patch({ name: event.currentTarget.value })} />
              </Field>
              <Field>
                <FieldLabel htmlFor={formId + '-prompt'}>{t('systemPrompt')}</FieldLabel>
                <Textarea id={formId + '-prompt'} rows={8} maxLength={100000} value={editor.value.system_prompt}
                  onChange={(event) => patch({ system_prompt: event.currentTarget.value })} />
              </Field>
            </FieldGroup>
          </TabsContent>
          <TabsContent value={kind}>
            <BindingsField items={resources} ids={editor.bindings} onChange={(bindings) => onChange({ ...editor, bindings })} />
          </TabsContent>
        </FieldSet>
      </div>
      {inline ? <div className="settings-form-actions">{saveButton}</div> : <DialogFooter>{saveButton}</DialogFooter>}
    </Tabs>
  );
}
