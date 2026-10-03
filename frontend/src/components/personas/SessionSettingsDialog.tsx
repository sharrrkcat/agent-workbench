import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Field, FieldLabel, FieldSet, FieldGroup } from '@/components/ui/field';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectGroup, SelectItem } from '@/components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { RefreshCw, Save } from 'lucide-react';
import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { knowledgeApi } from '../../api/knowledge';
import { chatApi } from '../../api/chat';
import { useModelsStore } from '../../store/useModelsStore';
import { usePersonasStore } from '../../store/usePersonasStore';
import { useCogitaStore } from '../../store/useCogitaStore';
import type { ChatDraft, OrdinaryChatDraft, OrdinarySession, Session, SessionPatch } from '../../types/chat';
import type { KnowledgeBase } from '../../types/knowledge';
import { Feedback, ResourceLoading, errorText } from '../settings/resources/ResourceUI';
import { ContextFields, GenerationFields, ModelField } from './ConfigurationFields';
import { SessionBindings } from './SessionBindings';
import { WorkspaceSessionSettingsDialog } from '../projects/WorkspaceSessionSettingsDialog';

type Tab = 'configuration' | 'knowledge';

export function SessionSettingsDialog(props: {
  session: Session | ChatDraft;
  onClose: () => void;
  onManagePersonas: () => void;
}) {
  return props.session.kind === 'workspace'
    ? <WorkspaceSessionSettingsDialog {...props} session={props.session} />
    : <OrdinarySessionSettingsDialog {...props} session={props.session} />;
}

function OrdinarySessionSettingsDialog({ session, onClose, onManagePersonas }: {
  session: OrdinarySession | OrdinaryChatDraft; onClose: () => void; onManagePersonas: () => void;
}) {
  const { confirm, confirmation } = useConfirmDialog();
  const { t } = useTranslation('personas');
  const formId = useId();
  const allPersonas = usePersonasStore((s) => s.personas);
  const personas = allPersonas.filter((p) => p.collection === 'agent');
  const profiles = useModelsStore((s) => s.profiles);
  const sessionId = 'session_id' in session ? session.session_id : null;
  const [draft, setDraft] = useState(() => structuredClone(session));
  const [tab, setTab] = useState<Tab>('configuration');
  const [knowledge, setKnowledge] = useState<string[]>([]);
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let live = true;
    setError('');
    void Promise.all([
      usePersonasStore.getState().reload(),
      sessionId ? knowledgeApi.listSessionKnowledgeBases(sessionId) : Promise.resolve({ knowledge_base_ids: (session as OrdinaryChatDraft).knowledge_base_ids }),
      knowledgeApi.listKnowledgeBases(),
      useModelsStore.getState().reload(),
    ]).then(([, kb, availableBases]) => {
      if (live) {
        const pending = useCogitaStore.getState().pendingKnowledge;
        setKnowledge(pending?.sessionId === sessionId ? pending.ids : kb.knowledge_base_ids);
        setBases(availableBases);
        setLoading(false);
      }
    }).catch((reason) => { if (live) setError(errorText(reason)); });
    return () => { live = false; };
  }, [sessionId, reload]);
  const patch = (values: Partial<OrdinaryChatDraft>) => setDraft((current) => ({ ...current, ...values }));
  async function save() {
    setBusy(true);
    if (sessionId) useCogitaStore.setState((state) => ({ savingSessionIds: [...state.savingSessionIds, sessionId] }));
    setError('');
    const values: SessionPatch = {
      ...(draft.title !== session.title ? { title: draft.title.trim() || (sessionId ? undefined : '') } : {}),
      persona_id: draft.persona_id,
      model_profile_id: draft.model_profile_id,
      context_policy: draft.context_policy,
      generation: draft.generation,
    };
    try {
      if (sessionId) {
        await chatApi.updateSession(sessionId, values);
        await knowledgeApi.updateSessionKnowledgeBases(sessionId, knowledge);
        useCogitaStore.setState((state) => state.pendingKnowledge?.sessionId === sessionId ? { pendingKnowledge: null } : {});
        await useCogitaStore.getState().reloadSessions();
      } else useCogitaStore.getState().saveDraft(values, knowledge);
      onClose();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      if (sessionId) useCogitaStore.setState((state) => ({ savingSessionIds: state.savingSessionIds.filter((id) => id !== sessionId) }));
      setBusy(false);
    }
  }
  return (
    <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose(); }}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader><DialogTitle>{t('sessionSettings')}</DialogTitle></DialogHeader>
        <Feedback error={error} />
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
