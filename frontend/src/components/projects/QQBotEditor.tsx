import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Field, FieldContent, FieldGroup, FieldLabel, FieldSet, FieldDescription } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectGroup, SelectItem } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { useModelsStore } from '../../store/useModelsStore';
import { usePersonasStore } from '../../store/usePersonasStore';
import { useProjectsStore } from '../../store/useProjectsStore';
import { useCogitaStore } from '../../store/useCogitaStore';
import { qqApi } from '../../api/qq';
import type { Project, QQBotProject, QQBotInput } from '../../types/projects';
import { ContextFields, GenerationFields, ModelField, ModelSelect } from '../personas/ConfigurationFields';
import { Feedback, ResourceLoading, errorText, type LeaveGuard } from '../settings/resources/ResourceUI';

export function qqInput(project?: QQBotProject, defaultPrompt = ''): QQBotInput {
  if (project) {
    const { id: _id, created_at: _created, updated_at: _updated, has_access_token: _has, ...values } = project;
    return values;
  }
  return { kind: 'qqbot', name: '', bot_account: '', websocket_url: 'ws://127.0.0.1:3001',
    connection_enabled: false, agent_persona_id: null, system_prompt: defaultPrompt, model_profile_id: null,
    temperature: null, reasoning: true, group_reply_mode: 'keyword', keywords: [], batch_message_limit: 20, reply_message_limit: 4, image_input_enabled: false,
    image_description_model_profile_id: null,
    context_policy: { max_messages: 100, max_chars: 100000, include_attachments: 'none' } };
}

export function QQBotEditor({ project, onSaved, onLeaveGuardChange, dialog = false }: {
  project?: QQBotProject; onSaved: (project: Project) => void;
  onLeaveGuardChange: (guard: LeaveGuard) => void; dialog?: boolean;
}) {
  const { t } = useTranslation('personas');
  const id = useId();
  const { confirm, confirmation } = useConfirmDialog();
  const [draft, setDraft] = useState(() => qqInput(project, t('qq.defaultPrompt')));
  const [baseline, setBaseline] = useState(() => JSON.stringify(draft));
  const [keywords, setKeywords] = useState(() => draft.keywords.join('\n'));
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [connection, setConnection] = useState('disabled');
  const personas = usePersonasStore((s) => s.personas);
  const profiles = useModelsStore((s) => s.profiles);
  const live = useRef(true);
  const dirty = JSON.stringify(draft) !== baseline;
  const status = useRef({ dirty, busy });
  status.current = { dirty, busy };
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
    let active = true;
    void Promise.all([useModelsStore.getState().reload(), usePersonasStore.getState().reload()])
      .then(() => { if (active) setLoading(false); }).catch((reason) => { if (active) setError(errorText(reason)); });
    return () => { active = false; };
  }, [reload]);
  useEffect(() => {
    if (!project) return;
    let active = true;
    const refresh = () => void qqApi.status(project.id).then((value) => { if (active) setConnection(value.status); })
      .catch((reason) => { if (active) setError(errorText(reason)); });
    refresh(); const timer = setInterval(refresh, 3000);
    return () => { active = false; clearInterval(timer); };
  }, [project?.id]);
  const update = (values: Partial<QQBotInput>) => setDraft((current) => ({ ...current, ...values }));
  async function save() {
    if (status.current.busy) return;
    status.current.busy = true; setBusy(true); setError(''); setNotice('');
    try {
      const saved = await useProjectsStore.getState().save(draft, project?.id);
      if (!live.current || saved.kind !== 'qqbot') return;
      const value = qqInput(saved);
      setDraft(value); setKeywords(value.keywords.join('\n')); setBaseline(JSON.stringify(value));
      status.current.dirty = false; setNotice(t('projectSaved'));
      void useCogitaStore.getState().refreshCurrent(); onSaved(saved);
    } catch (reason) { if (live.current) setError(errorText(reason)); }
    finally { status.current.busy = false; if (live.current) setBusy(false); }
  }
  if (loading) return <ResourceLoading error={error} retry={() => setReload((n) => n + 1)} />;
  return <form className={dialog ? 'settings-dialog-form' : 'flex min-w-0 flex-col gap-5'} onSubmit={(e) => { e.preventDefault(); void save(); }}>
    <Feedback error={error} notice={notice} />
    <div className={dialog ? 'settings-dialog-body' : 'min-w-0'}><FieldSet disabled={busy}><FieldGroup>
      <Field><FieldLabel htmlFor={id + '-name'}>{t('projectName')}</FieldLabel><Input id={id + '-name'} required maxLength={128} value={draft.name} onChange={(e) => update({ name: e.target.value })} /></Field>
      <Field><FieldLabel htmlFor={id + '-account'}>{t('qq.account')}</FieldLabel><Input id={id + '-account'} required inputMode="numeric" pattern="[1-9][0-9]{0,19}" value={draft.bot_account} onChange={(e) => update({ bot_account: e.target.value })} /></Field>
      <Field><FieldLabel htmlFor={id + '-url'}>{t('qq.url')}</FieldLabel><Input id={id + '-url'} required value={draft.websocket_url} onChange={(e) => update({ websocket_url: e.target.value })} /></Field>
      <Field><FieldLabel htmlFor={id + '-token'}>{t('qq.token')}</FieldLabel><Input id={id + '-token'} type="password" autoComplete="new-password" value={draft.access_token ?? ''} placeholder={project?.has_access_token && draft.access_token === undefined ? t('qq.tokenSaved') : ''} onChange={(e) => update({ access_token: e.target.value })} /><FieldDescription>{t('qq.tokenHint')}</FieldDescription>
        {project?.has_access_token ? <Button type="button" variant="outline" className="self-start" disabled={draft.access_token === ''} onClick={() => update({ access_token: '' })}>{t('qq.clearToken')}</Button> : null}
      </Field>
      <Field orientation="horizontal"><Switch id={id + '-enabled'} checked={draft.connection_enabled} onCheckedChange={(connection_enabled) => update({ connection_enabled })} /><FieldLabel htmlFor={id + '-enabled'}>{t('qq.enabled')}</FieldLabel><Badge variant="secondary">{t('qq.status.' + connection, { defaultValue: connection })}</Badge></Field>
      <ModelField profiles={profiles.filter((p) => p.source?.type === 'provider')} value={draft.model_profile_id} inheritLabel={t('selectModel')} onChange={(value) => update({ model_profile_id: value || null })} />
      <Field><FieldLabel htmlFor={id + '-persona'}>{t('defaultAgentPersona')}</FieldLabel>
        <Select value={draft.agent_persona_id ?? ''} onValueChange={(value) => update({ agent_persona_id: value || null })} items={[{ value: '', label: t('qq.noPersona') }, ...personas.filter((p) => p.collection === 'agent').map((p) => ({ value: p.id, label: p.name }))]}>
          <SelectTrigger id={id + '-persona'}><SelectValue /></SelectTrigger><SelectContent><SelectGroup><SelectItem value="">{t('qq.noPersona')}</SelectItem>{personas.filter((p) => p.collection === 'agent').map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectGroup></SelectContent>
        </Select><FieldDescription>{t('qq.personaHint')}</FieldDescription>
      </Field>
      <Field><FieldLabel htmlFor={id + '-prompt'}>{t('projectPrompt')}</FieldLabel><Textarea id={id + '-prompt'} rows={4} maxLength={100000} value={draft.system_prompt} onChange={(e) => update({ system_prompt: e.target.value })} /></Field>
      <Field><FieldLabel>{t('qq.replyMode')}</FieldLabel><Badge variant="secondary" className="self-start">{t('qq.keywordMode')}</Badge><FieldDescription>{t('qq.triggerHint')}</FieldDescription></Field>
      <Field><FieldLabel htmlFor={id + '-keywords'}>{t('qq.keywords')}</FieldLabel><Textarea id={id + '-keywords'} rows={3} value={keywords} onChange={(e) => { setKeywords(e.target.value); update({ keywords: e.target.value.split('\n').map((v) => v.trim()).filter(Boolean) }); }} /></Field>
      <Field><FieldLabel htmlFor={id + '-limit'}>{t('qq.batchLimit')}</FieldLabel><Input id={id + '-limit'} type="number" required min={1} max={200} value={draft.batch_message_limit} onChange={(e) => update({ batch_message_limit: Number(e.target.value) })} /></Field>
      <Field><FieldLabel htmlFor={id + '-reply-limit'}>{t('qq.replyLimit')}</FieldLabel><Input id={id + '-reply-limit'} type="number" required min={1} max={20} step={1} value={draft.reply_message_limit} onChange={(e) => update({ reply_message_limit: Number(e.target.value) })} /><FieldDescription>{t('qq.replyLimitHint')}</FieldDescription></Field>
      <Field orientation="horizontal"><Switch id={id + '-reasoning'} checked={draft.reasoning} onCheckedChange={(reasoning) => update({ reasoning })} /><FieldLabel htmlFor={id + '-reasoning'}>{t('qq.reasoning')}</FieldLabel></Field>
      <Field orientation="horizontal"><Switch id={id + '-images'} checked={draft.image_input_enabled} onCheckedChange={(image_input_enabled) => update({ image_input_enabled })} aria-describedby={id + '-images-hint'} />
        <FieldContent><FieldLabel htmlFor={id + '-images'}>{t('qq.imageInputEnabled')}</FieldLabel><FieldDescription id={id + '-images-hint'}>{t('qq.imageInputHint')}</FieldDescription></FieldContent>
      </Field>
      <Field><FieldLabel>{t('qq.imageDescriptionModel')}</FieldLabel>
        <ModelSelect profiles={profiles.filter((p) => p.source?.type === 'provider')}
          value={draft.image_description_model_profile_id} label={t('qq.imageDescriptionModel')}
          inheritLabel={t('qq.noDescriptionModel')} onChange={(value) => update({ image_description_model_profile_id: value || null })} />
        <FieldDescription>{t('qq.imageDescriptionHint')}</FieldDescription>
      </Field>
      <ContextFields showAttachments={false} value={draft.context_policy} onChange={(context_policy) => update({ context_policy: { ...context_policy, include_attachments: 'none' } })} />
      <GenerationFields value={{ temperature: draft.temperature }} onChange={(v) => update({ temperature: v.temperature ?? null })} />
      <Field><FieldDescription>{t('qq.harnessHint')}</FieldDescription></Field>
    </FieldGroup></FieldSet></div>
    <div className="settings-form-actions"><Button type="submit" disabled={busy || (!!project && !dirty)}>{t(project ? 'save' : 'createProject')}</Button></div>{confirmation}
  </form>;
}
