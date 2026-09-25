import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Field, FieldLabel, FieldSet, FieldGroup } from '@/components/ui/field';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectGroup, SelectItem } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { LockKeyhole, RefreshCw, Save } from 'lucide-react';
import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { knowledgeApi } from '../../api/knowledge';
import { chatApi } from '../../api/chat';
import { toolsApi } from '../../api/tools';
import { useModelsStore } from '../../store/useModelsStore';
import { usePersonasStore } from '../../store/usePersonasStore';
import { useCogitaStore } from '../../store/useCogitaStore';
import type { Session, SessionPatch } from '../../types/chat';
import type { HarnessTool } from '../../types/tools';
import type { KnowledgeBase } from '../../types/knowledge';
import { ResourceLoading, errorText } from '../settings/resources/ResourceUI';
import { BindingsField, ContextFields, GenerationFields, ModelField, ToolsField } from './ConfigurationFields';

type Tab = 'configuration' | 'knowledge';

export function SessionSettingsDialog({ session, onClose, onManagePersonas }: {
  session: Session;
  onClose: () => void;
  onManagePersonas: () => void;
}) {
  const { confirm, confirmation } = useConfirmDialog();
  const { t } = useTranslation('personas');
  const formId = useId();
  const allPersonas = usePersonasStore((s) => s.personas);
  const personas = allPersonas.filter((p) => p.collection === 'agent');
  const profiles = useModelsStore((s) => s.profiles);
  const [draft, setDraft] = useState<Session>(() => structuredClone(session));
  const [tab, setTab] = useState<Tab>('configuration');
  const [knowledge, setKnowledge] = useState<string[]>([]);
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [tools, setTools] = useState<HarnessTool[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let live = true;
    setError('');
    void Promise.all([
      usePersonasStore.getState().reload(),
      knowledgeApi.listSessionKnowledgeBases(session.session_id),
      knowledgeApi.listKnowledgeBases(),
      toolsApi.listTools(),
      useModelsStore.getState().reload(),
    ]).then(([, kb, availableBases, catalog]) => {
      if (live) {
        setKnowledge(kb.knowledge_base_ids);
        setBases(availableBases);
        setTools(catalog);
        setLoading(false);
      }
    }).catch((reason) => { if (live) setError(errorText(reason)); });
    return () => { live = false; };
  }, [session.session_id, reload]);
  const patch = (values: Partial<Session>) => setDraft((current) => ({ ...current, ...values }));
  async function save() {
    setBusy(true);
    setError('');
    const values: SessionPatch = {
      title: draft.title.trim() || undefined,
      persona_id: draft.persona_id,
      model_profile_id: draft.model_profile_id,
      context_policy: draft.context_policy,
      generation: draft.generation,
      harness_enabled: draft.harness_enabled,
      tools_allowed: draft.tools_allowed,
    };
    try {
      await chatApi.updateSession(session.session_id, values);
      await knowledgeApi.updateSessionKnowledgeBases(session.session_id, knowledge);
      await useCogitaStore.getState().reloadSessions();
      onClose();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose(); }}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader><DialogTitle>{t('sessionSettings')}</DialogTitle></DialogHeader>
        {error ? <p role="alert" className="model-feedback error-text">{error}</p> : null}
        {loading ? (
          <>
            <ResourceLoading error={error} />
            {error ? <Button variant="outline" onClick={() => setReload((value) => value + 1)}>
              <RefreshCw data-icon="inline-start" />{t('refresh')}
            </Button> : null}
          </>
        ) : (
          <Tabs value={tab} onValueChange={setTab} render={
            <form className="settings-dialog-form" onSubmit={(event) => { event.preventDefault(); void save(); }} />
          }>
            <TabsList aria-label={t('sessionSettings')}>
              <TabsTrigger value="configuration">{t('configuration')}</TabsTrigger>
              <TabsTrigger value="knowledge">{t('knowledge')}</TabsTrigger>
            </TabsList>
            <div className="settings-dialog-body">
              <FieldSet disabled={busy} className="model-form">
                <TabsContent value="configuration">
                  <FieldGroup>
                    <Field>
                      <FieldLabel htmlFor={formId + '-title'}>{t('sessionTitle')}</FieldLabel>
                      <Input id={formId + '-title'} value={draft.title} maxLength={120}
                        onChange={(event) => patch({ title: event.currentTarget.value })} />
                    </Field>
                    <Field>
                      <FieldLabel htmlFor={formId + '-persona'}>{t('agentPersona')}</FieldLabel>
                      <Select value={draft.persona_id} items={personas.map((p) => ({ value: p.id, label: p.name }))}
                        onValueChange={(value) => { if (value) patch({ persona_id: value }); }}>
                        <SelectTrigger id={formId + '-persona'}><SelectValue /></SelectTrigger>
                        <SelectContent><SelectGroup>
                          {personas.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
                        </SelectGroup></SelectContent>
                      </Select>
                    </Field>
                    <Button type="button" variant="outline" onClick={async () => {
                      if (await confirm(t('discardChanges'))) onManagePersonas();
                    }}>{t('manage')}</Button>
                    <ModelField profiles={profiles} value={draft.model_profile_id} onChange={(id) => patch({ model_profile_id: id })} />
                    <ContextFields value={draft.context_policy} onChange={(value) => patch({ context_policy: value })} />
                    <GenerationFields value={draft.generation} onChange={(value) => patch({ generation: value })} />
                    <Field orientation="horizontal">
                      <Switch id={formId + '-harness'} checked={draft.harness_enabled}
                        onCheckedChange={(value) => patch({ harness_enabled: value })} />
                      <FieldLabel htmlFor={formId + '-harness'}>{t('harnessEnabled')}</FieldLabel>
                    </Field>
                    <ToolsField tools={tools} value={draft.tools_allowed} onChange={(value) => patch({ tools_allowed: value })} />
                  </FieldGroup>
                </TabsContent>
                <TabsContent value="knowledge">
                  <SessionBindings personaId={draft.persona_id} userPersonaId={session.user_persona.id}
                    items={bases} ids={knowledge} onChange={setKnowledge} />
                </TabsContent>
              </FieldSet>
            </div>
            <DialogFooter><Button disabled={busy} type="submit"><Save data-icon="inline-start" />{t('save')}</Button></DialogFooter>
          </Tabs>
        )}
        {confirmation}
      </DialogContent>
    </Dialog>
  );
}

export function SessionBindings({ personaId, userPersonaId, items, ids, onChange }: {
  personaId: string;
  userPersonaId: string;
  items: Array<{ id: string; name: string; enabled: boolean }>;
  ids: string[];
  onChange: (ids: string[]) => void;
}) {
  const { t } = useTranslation('personas');
  const [bindings, setBindings] = useState<{ user: string[]; agent: string[] } | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let live = true;
    setBindings(null);
    setError('');
    void Promise.all([chatApi.getPersonaKnowledge(userPersonaId), chatApi.getPersonaKnowledge(personaId)])
      .then(([user, agent]) => { if (live) setBindings({ user: user.knowledge_base_ids, agent: agent.knowledge_base_ids }); })
      .catch((reason) => { if (live) setError(errorText(reason)); });
    return () => { live = false; };
  }, [personaId, userPersonaId, reload]);
  if (!bindings) return <>
    <ResourceLoading error={error} />
    {error ? <Button type="button" variant="outline" onClick={() => setReload((value) => value + 1)}>
      <RefreshCw data-icon="inline-start" />{t('refresh')}
    </Button> : null}
  </>;
  const inherited = new Set([...bindings.user, ...bindings.agent]);
  return (
    <div className="flex flex-col gap-4">
      {(['user', 'agent'] as const).map((collection) => (
        <section key={collection} aria-label={t(collection + 'PersonaBindings')}>
          <h3 className="binding-section-heading"><LockKeyhole size={15} aria-hidden="true" />{t(collection + 'PersonaBindings')}</h3>
          {bindings[collection].length ? (
            <BindingsField items={items.filter((item) => bindings[collection].includes(item.id))}
              ids={bindings[collection]} onChange={() => undefined} disabled />
          ) : <p className="model-empty">{t('noBindings')}</p>}
        </section>
      ))}
      <section aria-label={t('sessionAdditions')}>
        <h3>{t('sessionAdditions')}</h3>
        <BindingsField items={items.filter((item) => !inherited.has(item.id) || ids.includes(item.id))} ids={ids} onChange={onChange} />
      </section>
    </div>
  );
}
