import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Save } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldSet } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { knowledgeApi } from '../../api/knowledge';
import { toolsApi } from '../../api/tools';
import { worldbookApi } from '../../api/worldbook';
import { useModelsStore } from '../../store/useModelsStore';
import { usePersonasStore } from '../../store/usePersonasStore';
import { useCharactersStore } from '../../store/useCharactersStore';
import { useCogitaStore } from '../../store/useCogitaStore';
import { defaultContextPolicy, USER_PERSONA_ID } from '../../types/chat';
import type { Character, CharacterKind, NormalCharacter, NormalCharacterInput } from '../../types/characters';
import type { HarnessTool } from '../../types/tools';
import { BindingsField, ContextFields, GenerationFields, ModelField, PersonaField, ToolsField } from '../personas/ConfigurationFields';
import { IdentityAvatarField } from '../personas/IdentityAvatarField';
import { Feedback, ResourceLoading, errorText, type LeaveGuard } from '../settings/resources/ResourceUI';
import type { SettingsNavigate } from '../settings/navigation';
import { QQBotEditor } from './QQBotEditor';

type EditorProps = {
  character?: Character; kind: CharacterKind; onSaved: (character: Character) => void; onNavigate: SettingsNavigate;
  onLeaveGuardChange: (guard: LeaveGuard) => void; dialog?: boolean;
};
export function CharacterEditor(props: EditorProps) {
  if (props.kind === 'qqbot') return <QQBotEditor {...props} character={props.character?.kind === 'qqbot' ? props.character : undefined} />;
  return <NormalCharacterEditor {...props} character={props.character?.kind === 'normal' ? props.character : undefined} />;
}
export function characterInput(character: NormalCharacter): NormalCharacterInput {
  const { id: _id, is_protected: _protected, created_at: _created, updated_at: _updated, ...values } = character;
  return values;
}
export function newCharacterInput(tools: HarnessTool[], modelId: string | null): NormalCharacterInput {
  return { kind: 'normal', name: '', avatar_attachment_id: null, system_prompt: '', persona_id: USER_PERSONA_ID,
    model_profile_id: modelId, temperature: null, reasoning: true, context_policy: defaultContextPolicy(), harness_enabled: false,
    tools_allowed: tools.filter((tool) => tool.scope === 'general').map((tool) => tool.name), knowledge_base_ids: [], worldbook_ids: [] };
}
type Resource = { id: string; name: string; enabled: boolean };

function NormalCharacterEditor({ character, onSaved, onLeaveGuardChange, dialog = false }: Omit<EditorProps, 'character'> & { character?: NormalCharacter }) {
  const { t } = useTranslation('personas');
  const { confirm, confirmation } = useConfirmDialog();
  const formId = useId();
  const personas = usePersonasStore((state) => state.personas);
  const profiles = useModelsStore((state) => state.profiles);
  const [draft, setDraft] = useState<NormalCharacterInput | null>(() => character ? characterInput(character) : null);
  const [baseline, setBaseline] = useState(() => JSON.stringify(character ? characterInput(character) : null));
  const [bases, setBases] = useState<Resource[]>([]);
  const [books, setBooks] = useState<Resource[]>([]);
  const [tools, setTools] = useState<HarnessTool[]>([]);
  const [tab, setTab] = useState('identity');
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const live = useRef(true);
  const status = useRef({ dirty: false, busy: false });
  const dirty = JSON.stringify(draft) !== baseline;
  status.current = { dirty, busy: busy || uploading };
  const guard = useCallback<LeaveGuard>(async () => !status.current.busy &&
    (!status.current.dirty || await confirm(t('discardChanges'))), [confirm, t]);
  useEffect(() => { onLeaveGuardChange(guard); return () => onLeaveGuardChange(async () => true); }, [guard, onLeaveGuardChange]);
  useEffect(() => {
    live.current = true;
    const unload = (event: BeforeUnloadEvent) => { if (status.current.dirty || status.current.busy) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', unload);
    return () => { live.current = false; window.removeEventListener('beforeunload', unload); };
  }, []);
  useEffect(() => {
    let active = true; setError(''); setLoading(true);
    void Promise.all([knowledgeApi.listKnowledgeBases(), worldbookApi.listWorldbooks(), toolsApi.listTools(),
      usePersonasStore.getState().reload(), useModelsStore.getState().reloadProfiles(), useModelsStore.getState().reloadSettings(),
    ]).then(([bases, books, tools]) => {
      if (!active) return;
      setBases(bases); setBooks(books); setTools(tools.filter((tool) => tool.scope === 'general'));
      if (!draft) {
        const models = useModelsStore.getState();
        const enabled = models.profiles.filter((profile) => profile.kind === 'llm' && profile.enabled);
        const model = enabled.find((profile) => profile.id === models.settings?.default_model_profile_id) ?? enabled[0];
        const value = newCharacterInput(tools, model?.id ?? null);
        setBaseline(JSON.stringify(value)); setDraft(value);
      }
      setLoading(false);
    }).catch((reason) => { if (active) setError(errorText(reason)); });
    return () => { active = false; };
  }, [reload]);
  async function save() {
    if (!draft || status.current.busy) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const saved = await useCharactersStore.getState().save(draft, character?.id);
      if (!live.current || saved.kind !== 'normal') return;
      const value = characterInput(saved);
      setDraft(value); setBaseline(JSON.stringify(value)); status.current.dirty = false;
      setNotice(t('characterSaved')); void useCogitaStore.getState().refreshCurrent(); onSaved(saved);
    } catch (reason) { if (live.current) setError(errorText(reason)); }
    finally { if (live.current) setBusy(false); }
  }
  if (!draft) return <ResourceLoading error={error} retry={() => setReload((n) => n + 1)} />;
  const update = (values: Partial<NormalCharacterInput>) => setDraft((current) => current ? { ...current, ...values } : current);
  return <Tabs value={tab} onValueChange={setTab} render={<form className={dialog ? 'settings-dialog-form' : 'settings-form'}
    onInvalidCapture={(event) => { const panel = (event.target as HTMLElement).closest<HTMLElement>('[data-character-tab]'); if (panel) setTab(panel.dataset.characterTab!); }}
    onSubmit={(event) => { event.preventDefault(); void save(); }} />}>
    <Feedback error={error} notice={notice} />
    <TabsList aria-label={t('characterSettings')}>
      <TabsTrigger value="identity">{t('identity')}</TabsTrigger>
      <TabsTrigger value="configuration">{t('configuration')}</TabsTrigger>
      <TabsTrigger value="resources">{t('resources')}</TabsTrigger>
    </TabsList>
    <div className={dialog ? 'settings-dialog-body' : 'py-4'}><FieldSet disabled={busy}><FieldGroup>
      <TabsContent value="identity" keepMounted data-character-tab="identity"><FieldGroup>
        <IdentityAvatarField name={draft.name} value={draft.avatar_attachment_id} disabled={busy}
          onChange={(id) => update({ avatar_attachment_id: id })} onBusyChange={setUploading} onError={setError} />
        <Field><FieldLabel htmlFor={formId + '-name'}>{t('characterName')}</FieldLabel>
          <Input id={formId + '-name'} required maxLength={128} value={draft.name} onChange={(event) => update({ name: event.target.value })} /></Field>
        <Field><FieldLabel htmlFor={formId + '-prompt'}>{t('systemPrompt')}</FieldLabel>
          <Textarea id={formId + '-prompt'} rows={8} maxLength={100000} value={draft.system_prompt} onChange={(event) => update({ system_prompt: event.target.value })} /></Field>
      </FieldGroup></TabsContent>
      <TabsContent value="configuration" keepMounted data-character-tab="configuration"><FieldGroup>
        <PersonaField label={t('defaultPersona')} personas={personas} value={draft.persona_id} onChange={(id) => update({ persona_id: id })} />
        <ModelField profiles={profiles} value={draft.model_profile_id} inheritLabel={t('selectModel')} onChange={(id) => update({ model_profile_id: id || null })} />
        <GenerationFields value={{ temperature: draft.temperature }} onChange={(value) => update({ temperature: value.temperature ?? null })} />
        <Field orientation="horizontal"><Switch id={formId + '-reasoning'} checked={draft.reasoning} onCheckedChange={(reasoning) => update({ reasoning })} />
          <FieldLabel htmlFor={formId + '-reasoning'}>{t('reasoning')}</FieldLabel></Field>
        <Field orientation="horizontal"><Switch id={formId + '-harness'} checked={draft.harness_enabled} onCheckedChange={(harness_enabled) => update({ harness_enabled })} />
          <FieldLabel htmlFor={formId + '-harness'}>{t('harness')}</FieldLabel></Field>
        <ToolsField tools={tools} value={draft.tools_allowed} onChange={(tools_allowed) => update({ tools_allowed })} />
        <ContextFields value={draft.context_policy} harnessEnabled={draft.harness_enabled} onChange={(context_policy) => update({ context_policy })} />
      </FieldGroup></TabsContent>
      <TabsContent value="resources" keepMounted data-character-tab="resources"><FieldGroup>
        <Field><FieldDescription>{t('mountsInactive')}</FieldDescription></Field>
        <BindingsField label={t('knowledge')} items={bases} ids={draft.knowledge_base_ids} onChange={(knowledge_base_ids) => update({ knowledge_base_ids })} />
        <BindingsField label={t('worldbook')} items={books} ids={draft.worldbook_ids} onChange={(worldbook_ids) => update({ worldbook_ids })} />
      </FieldGroup></TabsContent>
    </FieldGroup></FieldSet></div>
    <div className="flex justify-end"><Button type="submit" disabled={busy || uploading || loading || !dirty}><Save data-icon="inline-start" />{t('save')}</Button></div>
    {confirmation}
  </Tabs>;
}
