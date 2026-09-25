import { useEffect, useId, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Save, Undo2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Field, FieldGroup, FieldLabel, FieldLegend, FieldSet } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { chatApi } from '../../api/chat';
import { knowledgeApi } from '../../api/knowledge';
import { toolsApi } from '../../api/tools';
import { useCogitaStore } from '../../store/useCogitaStore';
import { useModelsStore } from '../../store/useModelsStore';
import { usePersonasStore } from '../../store/usePersonasStore';
import { useProjectsStore } from '../../store/useProjectsStore';
import type { WorkspaceOverrides, WorkspaceSession } from '../../types/chat';
import type { WorkspaceProject } from '../../types/projects';
import type { KnowledgeBase } from '../../types/knowledge';
import type { HarnessTool } from '../../types/tools';
import { ContextFields, GenerationFields, ModelField, PersonaField, ToolsField } from '../personas/ConfigurationFields';
import { SessionBindings } from '../personas/SessionBindings';
import { Feedback, ResourceLoading, errorText } from '../settings/resources/ResourceUI';

function Inheritance({ label, inherited, onReset, children }: {
  label: string; inherited: boolean; onReset: () => void; children: ReactNode;
}) {
  const { t } = useTranslation('personas');
  return <FieldSet className="gap-3">
    <FieldLegend>{label}</FieldLegend>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="settings-note">{t(inherited ? 'inheritedFromProject' : 'sessionOverride')}</p>
      <Button type="button" variant="ghost" size="sm" disabled={inherited}
        aria-label={t('restoreInheritanceFor', { field: label })} onClick={onReset}>
        <Undo2 data-icon="inline-start" />{t('restoreInheritance')}
      </Button>
    </div>
    {children}
  </FieldSet>;
}

export function WorkspaceSessionSettingsDialog({ session, onClose, onManagePersonas }: {
  session: WorkspaceSession; onClose: () => void; onManagePersonas: () => void;
}) {
  const { t } = useTranslation('personas');
  const { confirm, confirmation } = useConfirmDialog();
  const formId = useId();
  const personas = usePersonasStore((state) => state.personas);
  const profiles = useModelsStore((state) => state.profiles);
  const globalModelId = useModelsStore((state) => state.settings?.default_model_profile_id);
  const sessionVersion = useCogitaStore((state) => state.sessionVersion);
  const [project, setProject] = useState<WorkspaceProject | null>(null);
  const [title, setTitle] = useState(session.title);
  const [changes, setChanges] = useState<WorkspaceOverrides>({});
  const [knowledge, setKnowledge] = useState<string[]>([]);
  const [originalKnowledge, setOriginalKnowledge] = useState<string[]>([]);
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [tools, setTools] = useState<HarnessTool[]>([]);
  const [tab, setTab] = useState<'configuration' | 'knowledge'>('configuration');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    if (!project) return;
    let live = true;
    void useProjectsStore.getState().load(session.project_id).then((value) => {
      if (live && value.kind === 'workspace') setProject(value);
    }).catch((reason) => { if (live) setError(errorText(reason)); });
    return () => { live = false; };
  }, [sessionVersion, session.project_id]);
  useEffect(() => {
    let live = true;
    setError('');
    void Promise.all([
      useProjectsStore.getState().load(session.project_id), usePersonasStore.getState().reload(),
      knowledgeApi.listSessionKnowledgeBases(session.session_id), knowledgeApi.listKnowledgeBases(),
      toolsApi.listTools(), useModelsStore.getState().reload(),
    ]).then(([project, , bindings, bases, tools]) => {
      if (!live) return;
      if (project.kind !== 'workspace') throw new Error(t('timelineCreationOnly'));
      setProject(project); setKnowledge(bindings.knowledge_base_ids); setOriginalKnowledge(bindings.knowledge_base_ids);
      setBases(bases); setTools(tools);
    }).catch((reason) => { if (live) setError(errorText(reason)); });
    return () => { live = false; };
  }, [session.project_id, session.session_id, reload]);
  const knowledgeChanged = JSON.stringify(knowledge) !== JSON.stringify(originalKnowledge);
  const dirty = title !== session.title || Object.keys(changes).length > 0 || knowledgeChanged;
  const canLeave = async () => !busy && (!dirty || await confirm(t('discardChanges')));
  async function close() { if (await canLeave()) onClose(); }
  async function save() {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const patch = { ...(title !== session.title ? { title: title.trim() } : {}),
        ...(Object.keys(changes).length ? { overrides: changes } : {}) };
      if (Object.keys(patch).length) await chatApi.updateSession(session.session_id, patch);
      if (knowledgeChanged) await knowledgeApi.updateSessionKnowledgeBases(session.session_id, knowledge);
      await useCogitaStore.getState().reloadSessions(session.project_id);
      onClose();
    } catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }
  const overrides = { ...session.overrides, ...changes };
  const change = <K extends keyof WorkspaceOverrides>(key: K, value: WorkspaceOverrides[K]) =>
    setChanges((current) => ({ ...current, [key]: value }));
  const inheritedModel = project?.model_profile_id ?? profiles.find((p) => p.kind === 'llm' && p.enabled && p.id === globalModelId)?.id
    ?? profiles.find((p) => p.kind === 'llm' && p.enabled)?.id ?? null;
  const inheritedModelName = profiles.find((p) => p.id === inheritedModel)?.name || t('noModels');
  const inheritance = (key: keyof WorkspaceOverrides, label: string, children: ReactNode) =>
    <Inheritance label={label} inherited={overrides[key] == null} onReset={() => change(key, null)}>{children}</Inheritance>;
  return <Dialog open onOpenChange={(open) => { if (!open) void close(); }}>
    <DialogContent className="sm:max-w-3xl">
      <DialogHeader><DialogTitle>{t('sessionSettings')}</DialogTitle></DialogHeader>
      {!project ? <ResourceLoading error={error} retry={() => setReload((n) => n + 1)} /> :
        <Tabs value={tab} onValueChange={setTab} render={<form className="settings-dialog-form" onSubmit={(event) => { event.preventDefault(); void save(); }} />}>
          <Feedback error={error} />
          <TabsList aria-label={t('sessionSettings')}>
            <TabsTrigger value="configuration">{t('configuration')}</TabsTrigger>
            <TabsTrigger value="knowledge">{t('knowledge')}</TabsTrigger>
          </TabsList>
          <div className="settings-dialog-body">
            <FieldSet disabled={busy} className="model-form">
              <TabsContent value="configuration">
                <FieldGroup>
                  <Field><FieldLabel htmlFor={formId + '-title'}>{t('sessionTitle')}</FieldLabel>
                    <Input id={formId + '-title'} value={title} maxLength={120} onChange={(event) => setTitle(event.currentTarget.value)} />
                  </Field>
                  {inheritance('persona_id', t('agentPersona'), <PersonaField label={t('agentPersona')}
                    personas={personas.filter((p) => p.collection === 'agent')} value={overrides.persona_id ?? project.agent_persona_id}
                    onChange={(id) => change('persona_id', id)} />)}
                  <Button type="button" variant="outline" onClick={async () => { if (await canLeave()) onManagePersonas(); }}>{t('manage')}</Button>
                  {inheritance('model_profile_id', t('model'), <ModelField profiles={profiles} value={overrides.model_profile_id ?? null}
                    inheritLabel={t('inheritProjectModel', { name: inheritedModelName })} onChange={(id) => change('model_profile_id', id || null)} />)}
                  {inheritance('context_policy', t('context'), <ContextFields value={overrides.context_policy ?? project.context_policy}
                    onChange={(value) => change('context_policy', value)} />)}
                  {inheritance('temperature', t('llm:params.temperature'), <GenerationFields value={{ temperature: overrides.temperature ?? project.temperature }}
                    onChange={(value) => change('temperature', value.temperature ?? null)} />)}
                  {inheritance('harness_enabled', t('harness'), <Field orientation="horizontal">
                    <Switch id={formId + '-harness'} checked={overrides.harness_enabled ?? project.harness_enabled} onCheckedChange={(value) => change('harness_enabled', value)} />
                    <FieldLabel htmlFor={formId + '-harness'}>{t('harnessEnabled')}</FieldLabel>
                  </Field>)}
                  {inheritance('tools_allowed', t('tools'), <ToolsField tools={tools} value={overrides.tools_allowed ?? project.tools_allowed}
                    allowed={project.tools_allowed} onChange={(value) => change('tools_allowed', value)} />)}
                </FieldGroup>
              </TabsContent>
              <TabsContent value="knowledge"><SessionBindings personaId={overrides.persona_id ?? project.agent_persona_id}
                userPersonaId={project.cogita_persona_id} projectIds={project.knowledge_base_ids} items={bases} ids={knowledge} onChange={setKnowledge} /></TabsContent>
            </FieldSet>
          </div>
          <DialogFooter><Button type="submit" disabled={busy || !dirty}><Save data-icon="inline-start" />{t('save')}</Button></DialogFooter>
        </Tabs>}
      {confirmation}
    </DialogContent>
  </Dialog>;
}
