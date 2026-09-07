import { Pencil, Plus, RefreshCw, Save, Trash2, Upload, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { knowledgeApi } from '../../api/knowledge';
import { worldbookApi } from '../../api/worldbook';
import { chatApi } from '../../api/chat';
import { ApiError } from '../../api/http';
import { usePersonasStore } from '../../store/usePersonasStore';
import { useModelsStore } from '../../store/useModelsStore';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { KnowledgeBase } from '../../types/knowledge';
import type { Persona, PersonaInput } from '../../types/chat';
import type { Worldbook } from '../../types/worldbook';
import { AppModal } from '../ui/AppModal';
import {
  BindingsField,
  Check,
  ContextFields,
  defaultPolicy,
  Field,
  GenerationFields,
  IconButton,
  ModelField,
  PersonaAvatar,
  ToolsField,
} from '../personas/ConfigurationFields';

type Editor = { id?: string; value: PersonaInput; knowledge: string[]; worldbooks: string[] };
type Tab = 'identity' | 'context' | 'knowledge' | 'worldbook';
const newPersona = (): PersonaInput => ({
  name: '',
  avatar_attachment_id: null,
  system_prompt: '',
  model_profile_id: null,
  context_policy: defaultPolicy(),
  generation: {},
  harness_enabled: false,
  tools_allowed: [],
});

export function PersonasPanel() {
  const { t } = useTranslation('personas');
  const personas = usePersonasStore((s) => s.personas);
  const reload = usePersonasStore((s) => s.reload);
  const storeError = usePersonasStore((s) => s.error);
  const profiles = useModelsStore((s) => s.profiles);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [tab, setTab] = useState<Tab>('identity');
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [worldbooks, setWorldbooks] = useState<Worldbook[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const upload = useRef<HTMLInputElement>(null);
  const temporaryAvatars = useRef(new Set<string>());

  async function load() {
    const [, , knowledge, books] = await Promise.all([
      reload(),
      useModelsStore.getState().reload(),
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
      const value = { ...editor.value, tools_allowed: editor.value.tools_allowed.map((s) => s.trim()).filter(Boolean) };
      const saved = editor.id ? await chatApi.patchPersona(editor.id, value) : await chatApi.createPersona(value);
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
          <IconButton label={t('refresh')} disabled={busy} onClick={() => void run(load)}>
            <RefreshCw size={16} />
          </IconButton>
          <button
            type="button"
            className="secondary-button"
            disabled={busy}
            onClick={() => {
              setError('');
              setTab('identity');
              setEditor({ value: newPersona(), knowledge: [], worldbooks: [] });
            }}
          >
            <Plus size={16} />
            {t('add')}
          </button>
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
              <small>
                {persona.model_profile_id
                  ? profiles.find((p) => p.id === persona.model_profile_id)?.name || t('unavailable')
                  : t('globalDefault')}
              </small>
              <small>{t('contextModes.' + persona.context_policy.mode)}</small>
            </div>
            <div className="model-actions">
              <IconButton
                label={t('editNamed', { name: persona.name })}
                disabled={busy}
                onClick={() => void edit(persona)}
              >
                <Pencil size={16} />
              </IconButton>
              <IconButton
                label={t('deleteNamed', { name: persona.name })}
                disabled={busy}
                onClick={() => {
                  if (window.confirm(t('deleteConfirm', { name: persona.name })))
                    void run(async () => {
                      await chatApi.deletePersona(persona.id);
                      await reload();
                    });
                }}
              >
                <Trash2 size={16} />
              </IconButton>
            </div>
          </div>
        ))}
      </div>
      <AppModal
        open={!!editor}
        title={editor?.id ? t('edit') : t('add')}
        closeLabel={t('close')}
        width="large"
        onClose={close}
      >
        {editor ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            {error ? (
              <p className="model-feedback error-text" role="alert">
                {error}
              </p>
            ) : null}
            <div className="model-tabs" role="tablist" aria-label={t('editorSections')}>
              {(['identity', 'context', 'knowledge', 'worldbook'] as Tab[]).map((key) => (
                <button type="button" role="tab" key={key} aria-selected={tab === key} onClick={() => setTab(key)}>
                  {t(key)}
                </button>
              ))}
            </div>
            <fieldset disabled={busy} className="model-form">
              {tab === 'identity' ? (
                <>
                  <div className="persona-avatar-editor">
                    <PersonaAvatar name={editor.value.name} attachmentId={editor.value.avatar_attachment_id} />
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
                    <IconButton label={t('uploadAvatar')} onClick={() => upload.current?.click()}>
                      <Upload size={17} />
                    </IconButton>
                    <IconButton
                      label={t('removeAvatar')}
                      disabled={!editor.value.avatar_attachment_id}
                      onClick={() => patch({ avatar_attachment_id: null })}
                    >
                      <X size={17} />
                    </IconButton>
                  </div>
                  <Field label={t('name')}>
                    <input
                      required
                      maxLength={128}
                      value={editor.value.name}
                      onChange={(e) => patch({ name: e.target.value })}
                    />
                  </Field>
                  <Field label={t('systemPrompt')}>
                    <textarea
                      rows={8}
                      maxLength={100000}
                      value={editor.value.system_prompt}
                      onChange={(e) => patch({ system_prompt: e.target.value })}
                    />
                  </Field>
                  <ModelField
                    profiles={profiles}
                    value={editor.value.model_profile_id}
                    onChange={(model_profile_id) => patch({ model_profile_id })}
                    inheritLabel={t('globalDefault')}
                  />
                  <h3>{t('generation')}</h3>
                  <GenerationFields value={editor.value.generation} onChange={(generation) => patch({ generation })} />
                </>
              ) : null}
              {tab === 'context' ? (
                <>
                  <ContextFields
                    value={editor.value.context_policy}
                    onChange={(context_policy) => patch({ context_policy })}
                  />
                  <h3>{t('harness')}</h3>
                  <p className="configuration-state">{t('harnessHelp')}</p>
                  <Check
                    label={t('harnessEnabled')}
                    checked={editor.value.harness_enabled}
                    onChange={(harness_enabled) => patch({ harness_enabled })}
                  />
                  <ToolsField
                    value={editor.value.tools_allowed}
                    onChange={(tools_allowed) => patch({ tools_allowed })}
                  />
                </>
              ) : null}
              {tab === 'knowledge' ? (
                <BindingsField
                  items={bases}
                  ids={editor.knowledge}
                  onChange={(knowledge) => setEditor({ ...editor, knowledge })}
                />
              ) : null}
              {tab === 'worldbook' ? (
                <BindingsField
                  items={worldbooks}
                  ids={editor.worldbooks}
                  onChange={(worldbooks) => setEditor({ ...editor, worldbooks })}
                />
              ) : null}
              <div className="model-form-footer">
                <button className="primary-button" type="submit">
                  <Save size={16} />
                  {t('save')}
                </button>
              </div>
            </fieldset>
          </form>
        ) : null}
      </AppModal>
    </section>
  );
}

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.code}: ${error.message}` : String(error);
}
