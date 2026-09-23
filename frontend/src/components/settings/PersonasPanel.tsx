import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Input } from '@/components/ui/input';
import { Field, FieldLabel, FieldSet } from '@/components/ui/field';
import { Textarea } from '@/components/ui/textarea';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Pencil, Plus, RefreshCw, Save, Trash2, Upload, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { knowledgeApi } from '../../api/knowledge';
import { worldbookApi } from '../../api/worldbook';
import { chatApi } from '../../api/chat';
import { ApiError } from '../../api/http';
import { usePersonasStore } from '../../store/usePersonasStore';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { KnowledgeBase } from '../../types/knowledge';
import type { Persona, PersonaInput } from '../../types/chat';
import type { Worldbook } from '../../types/worldbook';

import { BindingsField, PersonaAvatar } from '../personas/ConfigurationFields';

type Editor = { id?: string; value: PersonaInput; knowledge: string[]; worldbooks: string[] };
type Tab = 'identity' | 'knowledge' | 'worldbook';
const newPersona = (): PersonaInput => ({
  name: '',
  avatar_attachment_id: null,
  system_prompt: '',
});

export function PersonasPanel() {
  const { confirm, confirmation } = useConfirmDialog();
  const { t } = useTranslation('personas');
  const personas = usePersonasStore((s) => s.personas);
  const reload = usePersonasStore((s) => s.reload);
  const storeError = usePersonasStore((s) => s.error);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [tab, setTab] = useState<Tab>('identity');
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [worldbooks, setWorldbooks] = useState<Worldbook[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const upload = useRef<HTMLInputElement>(null);
  const temporaryAvatars = useRef(new Set<string>());

  async function load() {
    const [, knowledge, books] = await Promise.all([
      reload(),
      knowledgeApi.listKnowledgeBases(),
      worldbookApi.listWorldbooks(),
    ]);
    setBases(knowledge);
    setWorldbooks(books);
  }
  useEffect(() => {
    void load().catch((e) => setError(errorText(e)));
  }, []);

  async function run(task: () => Promise<void>) {
    setBusy(true);
    setError('');
    try {
      await task();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  function patch(values: Partial<PersonaInput>) {
    setEditor((current) => (current ? { ...current, value: { ...current.value, ...values } } : null));
  }
  async function edit(persona: Persona) {
    await run(async () => {
      const [knowledge, books] = await Promise.all([
        chatApi.getPersonaKnowledge(persona.id),
        chatApi.getPersonaWorldbooks(persona.id),
      ]);
      const { id, created_at, updated_at, ...value } = persona;
      setEditor({ id, value, knowledge: knowledge.knowledge_base_ids, worldbooks: books.worldbook_ids });
      setTab('identity');
    });
  }
  async function cleanupUploads() {
    const pending = [...temporaryAvatars.current];
    temporaryAvatars.current.clear();
    await Promise.allSettled(pending.map((id) => chatApi.deleteAttachment(id)));
  }
  function close() {
    if (busy) return;
    setEditor(null);
    setError('');
    void cleanupUploads();
  }
  async function save() {
    if (!editor) return;
    if (!editor.value.name.trim()) {
      setTab('identity');
      setError(t('nameRequired'));
      return;
    }
    await run(async () => {
      const value = editor.value;
      const saved = editor.id
        ? await chatApi.patchPersona(editor.id, value)
        : await chatApi.createPersona(value);
      setEditor({ ...editor, id: saved.id, value });
      if (saved.avatar_attachment_id) temporaryAvatars.current.delete(saved.avatar_attachment_id);
      await chatApi.patchPersonaKnowledge(saved.id, editor.knowledge);
      await chatApi.patchPersonaWorldbooks(saved.id, editor.worldbooks);
      await reload();
      await useWorkbenchStore.getState().reloadSessions();
      await cleanupUploads();
      setEditor(null);
    });
  }
  async function chooseAvatar(file: File | undefined) {
    if (!file) return;
    await run(async () => {
      const result = await chatApi.uploadAttachment(file);
      if (!result.uri) throw new Error(t('unavailable'));
      const attachmentId = new URL(result.uri).pathname.slice(1);
      temporaryAvatars.current.add(attachmentId);
      patch({ avatar_attachment_id: attachmentId });
    });
  }

  return (
    <section className="settings-panel personas-panel">
      <div className="model-heading">
        <h2>{t('title')}</h2>
        <div className="model-actions">
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={t('refresh')}
                  disabled={busy}
                  onClick={() => void run(load)}
                />
              }
            >
              <RefreshCw size={16} />
            </TooltipTrigger>
            <TooltipContent>{t('refresh')}</TooltipContent>
          </Tooltip>
          <Button
            type="button"
            disabled={busy}
            onClick={() => {
              setError('');
              setTab('identity');
              setEditor({ value: newPersona(), knowledge: [], worldbooks: [] });
            }}
            variant="outline"
          >
            <Plus size={16} />
            {t('add')}
          </Button>
        </div>
      </div>
      {!editor && (error || storeError) ? (
        <p className="model-feedback error-text" role="alert">
          {error || storeError}
        </p>
      ) : null}
      <div className="persona-list">
        {personas.map((persona) => (
          <div className="persona-row" key={persona.id}>
            <PersonaAvatar name={persona.name} attachmentId={persona.avatar_attachment_id} />
            <div className="persona-identity">
              <strong>{persona.name}</strong>
            </div>
            <div className="model-actions">
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={t('editNamed', { name: persona.name })}
                      disabled={busy}
                      onClick={() => void edit(persona)}
                    />
                  }
                >
                  <Pencil size={16} />
                </TooltipTrigger>
                <TooltipContent>{t('editNamed', { name: persona.name })}</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={t('deleteNamed', { name: persona.name })}
                      disabled={busy}
                      onClick={async () => {
                        if (await confirm(t('deleteConfirm', { name: persona.name }), { destructive: true }))
                          void run(async () => {
                            await chatApi.deletePersona(persona.id);
                            await reload();
                          });
                      }}
                    />
                  }
                >
                  <Trash2 size={16} />
                </TooltipTrigger>
                <TooltipContent>{t('deleteNamed', { name: persona.name })}</TooltipContent>
              </Tooltip>
            </div>
          </div>
        ))}
      </div>
      <Dialog
        open={!!editor}
        onOpenChange={(open) => {
          if (!open) close();
        }}
      >
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{editor?.id ? t('edit') : t('add')}</DialogTitle>
          </DialogHeader>
          <div className="min-h-0 overflow-y-auto overscroll-contain">
            {editor ? (
              <Tabs
                value={tab}
                onValueChange={setTab}
                render={
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      void save();
                    }}
                  />
                }
              >
                {error ? (
                  <p className="model-feedback error-text" role="alert">
                    {error}
                  </p>
                ) : null}
                <TabsList className="model-tabs" aria-label={t('editorSections')}>
                  {(['identity', 'knowledge', 'worldbook'] as Tab[]).map((key) => (
                    <TabsTrigger value={key} key={key}>
                      {t(key)}
                    </TabsTrigger>
                  ))}
                </TabsList>
                <FieldSet disabled={busy} className="model-form">
                  <TabsContent value="identity">
                    <>
                      <div className="persona-avatar-editor">
                        <PersonaAvatar
                          name={editor.value.name}
                          attachmentId={editor.value.avatar_attachment_id}
                        />
                        <input
                          ref={upload}
                          type="file"
                          hidden
                          accept="image/png,image/jpeg,image/webp,image/gif"
                          onChange={(e) => {
                            const file = e.target.files?.[0];
                            e.target.value = '';
                            void chooseAvatar(file);
                          }}
                        />
                        <Tooltip>
                          <TooltipTrigger
                            render={
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                aria-label={t('uploadAvatar')}
                                onClick={() => upload.current?.click()}
                              />
                            }
                          >
                            <Upload size={17} />
                          </TooltipTrigger>
                          <TooltipContent>{t('uploadAvatar')}</TooltipContent>
                        </Tooltip>
                        <Tooltip>
                          <TooltipTrigger
                            render={
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                aria-label={t('removeAvatar')}
                                disabled={!editor.value.avatar_attachment_id}
                                onClick={() => patch({ avatar_attachment_id: null })}
                              />
                            }
                          >
                            <X size={17} />
                          </TooltipTrigger>
                          <TooltipContent>{t('removeAvatar')}</TooltipContent>
                        </Tooltip>
                      </div>
                      <Field>
                        <FieldLabel>{t('name')}</FieldLabel>
                        <Input
                          required
                          maxLength={128}
                          value={editor.value.name}
                          onChange={(e) => patch({ name: e.target.value })}
                        />
                      </Field>
                      <Field>
                        <FieldLabel>{t('systemPrompt')}</FieldLabel>
                        <Textarea
                          rows={8}
                          maxLength={100000}
                          value={editor.value.system_prompt}
                          onChange={(e) => patch({ system_prompt: e.target.value })}
                        ></Textarea>
                      </Field>
                    </>
                  </TabsContent>
                  <TabsContent value="knowledge">
                    <BindingsField
                      items={bases}
                      ids={editor.knowledge}
                      onChange={(knowledge) => setEditor({ ...editor, knowledge })}
                    />
                  </TabsContent>
                  <TabsContent value="worldbook">
                    <BindingsField
                      items={worldbooks}
                      ids={editor.worldbooks}
                      onChange={(worldbooks) => setEditor({ ...editor, worldbooks })}
                    />
                  </TabsContent>
                  <div className="model-form-footer">
                    <Button type="submit" variant="default">
                      <Save size={16} />
                      {t('save')}
                    </Button>
                  </div>
                </FieldSet>
              </Tabs>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>
      {confirmation}
    </section>
  );
}

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.code}: ${error.message}` : String(error);
}
