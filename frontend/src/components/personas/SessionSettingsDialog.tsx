import { useEffect, useId, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Save, Undo2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Field, FieldDescription, FieldGroup, FieldLabel, FieldLegend, FieldSet } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { chatApi } from '../../api/chat';
import { knowledgeApi } from '../../api/knowledge';
import { worldbookApi } from '../../api/worldbook';
import { toolsApi } from '../../api/tools';
import { useCogitaStore } from '../../store/useCogitaStore';
import { useModelsStore } from '../../store/useModelsStore';
import { usePersonasStore } from '../../store/usePersonasStore';
import { useCharactersStore } from '../../store/useCharactersStore';
import type { ChatDraft, SessionOverrides, NormalSession } from '../../types/chat';
import type { HarnessTool } from '../../types/tools';
import { BindingsField, ContextFields, GenerationFields, ModelField, PersonaField, ToolsField } from './ConfigurationFields';
import { Feedback, ResourceLoading, errorText } from '../settings/resources/ResourceUI';

function Inheritance({ label, inherited, onReset, children }: {
  label: string; inherited: boolean; onReset: () => void; children: ReactNode;
}) {
  const { t } = useTranslation('personas');
  return <FieldSet className="gap-3">
    <FieldLegend>{label}</FieldLegend>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="settings-note">{t(inherited ? 'inheritedFromCharacter' : 'sessionOverride')}</p>
      <Button type="button" variant="ghost" size="sm" disabled={inherited}
        aria-label={t('restoreInheritanceFor', { field: label })} onClick={onReset}>
        <Undo2 data-icon="inline-start" />{t('restoreInheritance')}
      </Button>
    </div>
    {children}
  </FieldSet>;
}

type Resource = { id: string; name: string; enabled: boolean };
export function SessionSettingsDialog({ session, onClose, onManagePersonas }: {
  session: NormalSession | ChatDraft; onClose: () => void; onManagePersonas: () => void;
}) {
  const { t } = useTranslation('personas');
  const { confirm, confirmation } = useConfirmDialog();
  const formId = useId();
  const sessionId = 'session_id' in session ? session.session_id : null;
  const personas = usePersonasStore((state) => state.personas);
  const profiles = useModelsStore((state) => state.profiles);
  const owner = useCharactersStore((state) => state.characters.find((item) => item.id === session.character_id));
  const character = owner?.kind === 'normal' ? owner : null;
  const [title, setTitle] = useState(session.title);
  const [changes, setChanges] = useState<SessionOverrides>({});
  const [bases, setBases] = useState<Resource[]>([]);
  const [books, setBooks] = useState<Resource[]>([]);
  const [tools, setTools] = useState<HarnessTool[]>([]);
  const [tab, setTab] = useState('configuration');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let live = true; setError(''); setLoading(true);
    void Promise.all([
      useCharactersStore.getState().load(session.character_id), usePersonasStore.getState().reload(),
      knowledgeApi.listKnowledgeBases(), worldbookApi.listWorldbooks(), toolsApi.listTools(),
      useModelsStore.getState().reloadProfiles(),
    ]).then(([, , bases, books, tools]) => {
      if (live) { setBases(bases); setBooks(books); setTools(tools.filter((tool) => tool.scope === 'general')); setLoading(false); }
    }).catch((reason) => { if (live) setError(errorText(reason)); });
    return () => { live = false; };
  }, [session.character_id, reload]);
  const dirty = title !== session.title || Object.keys(changes).length > 0;
  const canLeave = async () => !busy && (!dirty || await confirm(t('discardChanges')));
  async function close() { if (await canLeave()) onClose(); }
  async function save() {
    if (busy) return;
    setBusy(true); setError('');
    if (sessionId) useCogitaStore.setState((state) => ({ savingSessionIds: [...state.savingSessionIds, sessionId] }));
    try {
      const patch = { ...(title !== session.title ? { title: title.trim() } : {}),
        ...(Object.keys(changes).length ? { overrides: changes } : {}) };
      if (sessionId) {
        await chatApi.updateSession(sessionId, patch);
        await useCogitaStore.getState().reloadSessions(session.character_id);
      } else useCogitaStore.getState().saveDraft(patch);
      onClose();
    } catch (reason) { setError(errorText(reason)); }
    finally {
      if (sessionId) useCogitaStore.setState((state) => ({ savingSessionIds: state.savingSessionIds.filter((id) => id !== sessionId) }));
      setBusy(false);
    }
  }
  const overrides = { ...session.overrides, ...changes };
  const change = <K extends keyof SessionOverrides>(key: K, value: SessionOverrides[K]) => setChanges((current) => ({ ...current, [key]: value }));
  const inheritedModelName = profiles.find((p) => p.id === character?.model_profile_id)?.name || t('noModels');
  const inheritance = (key: keyof SessionOverrides, label: string, children: ReactNode) =>
    <Inheritance label={label} inherited={overrides[key] == null} onReset={() => change(key, null)}>{children}</Inheritance>;
  return <Dialog open onOpenChange={(open) => { if (!open) void close(); }}>
    <DialogContent className="sm:max-w-3xl">
      <DialogHeader><DialogTitle>{t('sessionSettings')}</DialogTitle></DialogHeader>
      {!character || loading ? <ResourceLoading error={error} retry={() => setReload((n) => n + 1)} /> :
        <Tabs value={tab} onValueChange={setTab} render={<form className="settings-dialog-form" onSubmit={(event) => { event.preventDefault(); void save(); }} />}>
          <Feedback error={error} />
          <TabsList aria-label={t('sessionSettings')}>
            <TabsTrigger value="configuration">{t('configuration')}</TabsTrigger>
            <TabsTrigger value="resources">{t('resources')}</TabsTrigger>
          </TabsList>
          <div className="settings-dialog-body"><FieldSet disabled={busy} className="model-form">
            <TabsContent value="configuration"><FieldGroup>
              <Field><FieldLabel htmlFor={formId + '-title'}>{t('sessionTitle')}</FieldLabel>
                <Input id={formId + '-title'} value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} /></Field>
              {inheritance('persona_id', t('persona'), <PersonaField label={t('persona')} personas={personas}
                value={overrides.persona_id ?? character.persona_id} onChange={(id) => change('persona_id', id)} />)}
              <Button type="button" variant="outline" onClick={async () => { if (await canLeave()) onManagePersonas(); }}>{t('manage')}</Button>
              {inheritance('model_profile_id', t('model'), <ModelField profiles={profiles} value={overrides.model_profile_id ?? null}
                inheritLabel={t('inheritCharacterModel', { name: inheritedModelName })} onChange={(id) => change('model_profile_id', id || null)} />)}
              {inheritance('temperature', t('llm:params.temperature'), <GenerationFields value={{ temperature: overrides.temperature ?? character.temperature }}
                onChange={(value) => change('temperature', value.temperature ?? null)} />)}
              {inheritance('reasoning', t('reasoning'), <Field orientation="horizontal"><Switch id={formId + '-reasoning'}
                checked={overrides.reasoning ?? character.reasoning} onCheckedChange={(value) => change('reasoning', value)} /><FieldLabel htmlFor={formId + '-reasoning'}>{t('reasoning')}</FieldLabel></Field>)}
              {inheritance('harness_enabled', t('harness'), <Field orientation="horizontal"><Switch id={formId + '-harness'}
                checked={overrides.harness_enabled ?? character.harness_enabled} onCheckedChange={(value) => change('harness_enabled', value)} /><FieldLabel htmlFor={formId + '-harness'}>{t('harness')}</FieldLabel></Field>)}
              {inheritance('tools_allowed', t('tools'), <ToolsField tools={tools} value={overrides.tools_allowed ?? character.tools_allowed}
                onChange={(value) => change('tools_allowed', value)} />)}
              {inheritance('context_policy', t('context'), <ContextFields harnessEnabled={overrides.harness_enabled ?? character.harness_enabled}
                value={overrides.context_policy ?? character.context_policy} onChange={(value) => change('context_policy', value)} />)}
            </FieldGroup></TabsContent>
            <TabsContent value="resources"><FieldGroup>
              <Field><FieldDescription>{t('mountsInactive')}</FieldDescription></Field>
              {inheritance('knowledge_base_ids', t('knowledge'), <BindingsField items={bases}
                ids={overrides.knowledge_base_ids ?? character.knowledge_base_ids} onChange={(value) => change('knowledge_base_ids', value)} />)}
              {inheritance('worldbook_ids', t('worldbook'), <BindingsField items={books}
                ids={overrides.worldbook_ids ?? character.worldbook_ids} onChange={(value) => change('worldbook_ids', value)} />)}
            </FieldGroup></TabsContent>
          </FieldSet></div>
          <DialogFooter><Button type="submit" disabled={busy || !dirty}><Save data-icon="inline-start" />{t('save')}</Button></DialogFooter>
        </Tabs>}
      {confirmation}
    </DialogContent>
  </Dialog>;
}
