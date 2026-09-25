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
import { useProjectsStore } from '../../store/useProjectsStore';
import { useCogitaStore } from '../../store/useCogitaStore';
import type { Persona, PersonaCollection } from '../../types/chat';
import type { Project, ProjectInput, ProjectKind } from '../../types/projects';
import type { HarnessTool } from '../../types/tools';
import { BindingsField, ContextFields, GenerationFields, ModelField, PersonaAvatar, PersonaField, ToolsField } from '../personas/ConfigurationFields';
import { Feedback, ResourceLoading, errorText, type LeaveGuard } from '../settings/resources/ResourceUI';
import { settingsRouteUrl, type SettingsNavigate } from '../settings/navigation';

export function projectInput(project: Project): ProjectInput {
  const { id: _id, created_at: _created, updated_at: _updated, ...values } = project;
  return values;
}

export function newProjectInput(kind: ProjectKind, personas: Persona[], tools: HarnessTool[]): ProjectInput {
  const common = { name: '', model_profile_id: null, temperature: null,
    context_policy: { mode: 'session' as const, max_messages: null, max_chars: null, include_attachments: 'explicit' as const } };
  return kind === 'workspace' ? { ...common, kind,
    agent_persona_id: personas.find((p) => p.collection === 'agent' && p.is_protected)?.id || '',
    cogita_persona_id: personas.find((p) => p.collection === 'user')?.id || '',
    harness_enabled: false, tools_allowed: tools.map((tool) => tool.name), system_prompt: '', knowledge_base_ids: [],
  } : { ...common, kind, character_persona_id: '', user_persona_id: '', worldbook_ids: [] };
}

export function ProjectEditor({ project, kind, onSaved, onNavigate, onLeaveGuardChange, dialog = false }: {
  project?: Project; kind: ProjectKind; onSaved: (project: Project) => void; onNavigate: SettingsNavigate;
  onLeaveGuardChange: (guard: LeaveGuard) => void; dialog?: boolean;
}) {
  const { t } = useTranslation('personas');
  const { confirm, confirmation } = useConfirmDialog();
  const formId = useId();
  const personas = usePersonasStore((state) => state.personas);
  const profiles = useModelsStore((state) => state.profiles);
  const [draft, setDraft] = useState<ProjectInput | null>(() => project ? projectInput(project) : null);
  const [baseline, setBaseline] = useState(() => JSON.stringify(project ? projectInput(project) : null));
  const [resources, setResources] = useState<Array<{ id: string; name: string; enabled: boolean }>>([]);
  const [tools, setTools] = useState<HarnessTool[]>([]);
  const [tab, setTab] = useState<'configuration' | 'resources'>('configuration');
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(false);
  const [invalid, setInvalid] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const live = useRef(true);
  const dirty = JSON.stringify(draft) !== baseline;
  const status = useRef({ dirty, busy });
  status.current = { dirty, busy };
  const guard = useCallback<LeaveGuard>(async () => !status.current.busy &&
    (!status.current.dirty || await confirm(t('discardChanges'))), [confirm, t]);
  useEffect(() => {
    onLeaveGuardChange(guard);
    return () => onLeaveGuardChange(async () => true);
  }, [guard, onLeaveGuardChange]);
  useEffect(() => {
    const unload = (event: BeforeUnloadEvent) => { if (status.current.dirty || status.current.busy) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', unload);
    return () => window.removeEventListener('beforeunload', unload);
  }, []);
  useEffect(() => {
    live.current = true;
    return () => { live.current = false; };
  }, []);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    void Promise.all([
      usePersonasStore.getState().reload(), useModelsStore.getState().reload(),
      kind === 'workspace' ? knowledgeApi.listKnowledgeBases() : worldbookApi.listWorldbooks(),
      kind === 'workspace' ? toolsApi.listTools() : Promise.resolve([] as HarnessTool[]),
    ]).then(([, , available, catalog]) => {
      if (!active) return;
      setResources(available);
      setTools(catalog);
      if (!project) {
        const initial = newProjectInput(kind, usePersonasStore.getState().personas, catalog);
        setDraft(initial);
        setBaseline(JSON.stringify(initial));
      }
      setLoading(false);
    }).catch((reason) => { if (active) setError(errorText(reason)); });
    return () => { active = false; };
  }, [kind, project?.id, reload]);

  async function save() {
    if (!draft || status.current.busy) return;
    if (!draft.name.trim() || (draft.kind === 'workspace' ? !draft.agent_persona_id || !draft.cogita_persona_id
      : !draft.character_persona_id || !draft.user_persona_id)) {
      setInvalid(true); setTab('configuration'); setError(t('projectRequired')); return;
    }
    status.current.busy = true;
    setBusy(true); setError(''); setNotice('');
    try {
      const saved = await useProjectsStore.getState().save(draft, project?.id);
      if (!live.current) return;
      const values = projectInput(saved);
      setDraft(values); setBaseline(JSON.stringify(values)); setNotice(t('projectSaved'));
      status.current = { dirty: false, busy: false };
      void useCogitaStore.getState().refreshCurrent();
      onSaved(saved);
    } catch (reason) {
      if (live.current) setError(errorText(reason));
    } finally {
      status.current.busy = false;
      if (live.current) setBusy(false);
    }
  }

  function manage(collection: PersonaCollection) {
    return <Button type="button" variant="outline" onClick={() => void onNavigate(settingsRouteUrl({ section: 'personas', view: collection }))}>
      {t('manageCollection', { collection: t('collections.' + collection) })}
    </Button>;
  }
  if (loading || !draft) return <ResourceLoading error={error} retry={() => setReload((n) => n + 1)} />;
  const cogita = draft.kind === 'workspace' ? personas.find((p) => p.id === draft.cogita_persona_id) : null;
  return (
    <Tabs value={tab} onValueChange={setTab} render={<form className={dialog ? 'settings-dialog-form' : 'flex min-w-0 flex-col gap-5'}
      onSubmit={(event) => { event.preventDefault(); void save(); }} />}>
      <Feedback error={error} notice={notice} />
      <TabsList aria-label={t('projectSettings')}>
        <TabsTrigger value="configuration">{t('configuration')}</TabsTrigger>
        <TabsTrigger value="resources">{t(kind === 'workspace' ? 'knowledge' : 'worldbook')}</TabsTrigger>
      </TabsList>
      <div className={dialog ? 'settings-dialog-body' : 'min-w-0'}>
        <FieldSet disabled={busy} className="model-form">
          <TabsContent value="configuration">
            <FieldGroup>
              <Field data-invalid={(invalid && !draft.name.trim()) || undefined}>
                <FieldLabel htmlFor={formId + '-name'}>{t('projectName')}</FieldLabel>
                <Input id={formId + '-name'} value={draft.name} required maxLength={128} aria-invalid={invalid && !draft.name.trim()}
                  onChange={(event) => setDraft({ ...draft, name: event.currentTarget.value })} />
              </Field>
              {draft.kind === 'workspace' ? <>
                <PersonaField label={t('defaultAgentPersona')} personas={personas.filter((p) => p.collection === 'agent')}
                  value={draft.agent_persona_id} invalid={invalid && !draft.agent_persona_id} onChange={(id) => setDraft({ ...draft, agent_persona_id: id })} />
                {manage('agent')}
                <Field>
                  <FieldLabel>{t('collections.user')}</FieldLabel>
                  <div className="flex items-center gap-3">
                    {cogita ? <PersonaAvatar name={cogita.name} attachmentId={cogita.avatar_attachment_id} /> : null}
                    <span>{cogita?.name || t('unavailable')}</span>
                  </div>
                  <FieldDescription>{t('fixedCogitaPersona')}</FieldDescription>
                </Field>
                <Field>
                  <FieldLabel htmlFor={formId + '-prompt'}>{t('projectPrompt')}</FieldLabel>
                  <Textarea id={formId + '-prompt'} rows={4} maxLength={100000} value={draft.system_prompt}
                    onChange={(event) => setDraft({ ...draft, system_prompt: event.currentTarget.value })} />
                </Field>
              </> : <>
                <PersonaField label={t('characterPersona')} personas={personas.filter((p) => p.collection === 'character')}
                  value={draft.character_persona_id} invalid={invalid && !draft.character_persona_id} onChange={(id) => setDraft({ ...draft, character_persona_id: id })} />
                {manage('character')}
                <PersonaField label={t('timelineUserPersona')} personas={personas.filter((p) => p.collection === 'roleplay_user')}
                  value={draft.user_persona_id} invalid={invalid && !draft.user_persona_id} onChange={(id) => setDraft({ ...draft, user_persona_id: id })} />
                {manage('roleplay_user')}
                <p className="settings-note">{t('timelineCreationOnly')}</p>
              </>}
              <ModelField profiles={profiles} value={draft.model_profile_id} inheritLabel={t('inheritGlobalModel')}
                onChange={(id) => setDraft({ ...draft, model_profile_id: id || null })} />
              <ContextFields value={draft.context_policy} onChange={(value) => setDraft({ ...draft, context_policy: value })} />
              <GenerationFields value={{ temperature: draft.temperature }} onChange={(value) => setDraft({ ...draft, temperature: value.temperature ?? null })} />
              {draft.kind === 'workspace' ? <>
                <Field orientation="horizontal">
                  <Switch id={formId + '-harness'} checked={draft.harness_enabled} onCheckedChange={(value) => setDraft({ ...draft, harness_enabled: value })} />
                  <FieldLabel htmlFor={formId + '-harness'}>{t('harnessEnabled')}</FieldLabel>
                </Field>
                <ToolsField tools={tools} value={draft.tools_allowed} onChange={(value) => setDraft({ ...draft, tools_allowed: value })} />
              </> : null}
            </FieldGroup>
          </TabsContent>
          <TabsContent value="resources">
            <FieldGroup>
              <p className="settings-note">{t(kind === 'workspace' ? 'projectKnowledgeHint' : 'projectWorldbookHint')}</p>
              <BindingsField items={resources} ids={draft.kind === 'workspace' ? draft.knowledge_base_ids : draft.worldbook_ids}
                onChange={(ids) => setDraft(draft.kind === 'workspace' ? { ...draft, knowledge_base_ids: ids } : { ...draft, worldbook_ids: ids })} />
            </FieldGroup>
          </TabsContent>
        </FieldSet>
      </div>
      <div className="settings-form-actions"><Button type="submit" disabled={busy || (!!project && !dirty)}>
        <Save data-icon="inline-start" />{t(project ? 'save' : 'createProject')}
      </Button></div>
      {confirmation}
    </Tabs>
  );
}
