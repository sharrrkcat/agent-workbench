import { ArrowDown, ArrowUp, LockKeyhole, Plus, RefreshCw, Save, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { knowledgeApi } from '../../api/knowledge';
import { worldbookApi } from '../../api/worldbook';
import { chatApi } from '../../api/chat';
import { toolsApi } from '../../api/tools';
import { ApiError } from '../../api/http';
import { useModelsStore } from '../../store/useModelsStore';
import { usePersonasStore } from '../../store/usePersonasStore';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { Session, SessionPatch, SessionPersona } from '../../types/chat';
import type { HarnessTool } from '../../types/tools';
import type { KnowledgeBase } from '../../types/knowledge';
import type { Worldbook } from '../../types/worldbook';
import { AppModal } from '../ui/AppModal';
import { BindingsField, Check, ContextFields, Field, GenerationFields, IconButton, ModelField, PersonaAvatar, ToolsField } from './ConfigurationFields';

type Tab = 'members' | 'configuration' | 'knowledge' | 'worldbook';

export function SessionSettingsDialog({ session, onClose, onManagePersonas }: { session: Session; onClose: () => void; onManagePersonas: () => void }) {
  const { t } = useTranslation('personas');
  const personas = usePersonasStore((s) => s.personas);
  const profiles = useModelsStore((s) => s.profiles);
  const [draft, setDraft] = useState<Session>(() => structuredClone(session));
  const [tab, setTab] = useState<Tab>('members');
  const [knowledge, setKnowledge] = useState<string[]>([]);
  const [books, setBooks] = useState<string[]>([]);
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [worldbooks, setWorldbooks] = useState<Worldbook[]>([]);
  const [tools, setTools] = useState<HarnessTool[]>([]);
  const [memberId, setMemberId] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let live = true;
    setError('');
    void Promise.all([usePersonasStore.getState().reload(), knowledgeApi.listSessionKnowledgeBases(session.session_id), worldbookApi.getSessionWorldbooks(session.session_id), knowledgeApi.listKnowledgeBases(), worldbookApi.listWorldbooks(), toolsApi.listTools(), useModelsStore.getState().reload()])
      .then(([, kb, wb, bases, worldbooks, catalog]) => { if (live) { setKnowledge(kb.knowledge_base_ids); setBooks(wb.worldbook_ids); setBases(bases); setWorldbooks(worldbooks); setTools(catalog); setLoading(false); } })
      .catch((e) => { if (live) setError(String(e)); });
    return () => { live = false; };
  }, [session.session_id, reload]);
  const patch = (values: Partial<Session>) => setDraft((current) => ({ ...current, ...values }));
  const available = personas.filter((p) => !draft.personas.some((m) => m.persona_id === p.id));
  const move = (index: number, delta: number) => {
    const members = [...draft.personas];
    [members[index], members[index + delta]] = [members[index + delta], members[index]];
    patch({ personas: members });
  };
  const changeMember = (id: string, values: Partial<SessionPersona>) => patch({ personas: draft.personas.map((m) => m.persona_id === id ? { ...m, ...values } : m) });
  async function save() {
    setBusy(true); setError('');
    const values: SessionPatch = {
      title: draft.title.trim() || undefined, context_mode: draft.context_mode, current_persona_id: draft.current_persona_id,
      personas: draft.personas.map(({ persona_id, enabled }) => ({ persona_id, enabled })),
      model_profile_id: draft.model_profile_id, context_policy: draft.context_policy,
      generation: draft.generation, harness_enabled: draft.harness_enabled,
      tools_allowed: draft.tools_allowed,
    };
    try {
      await chatApi.updateSession(session.session_id, values);
      await knowledgeApi.updateSessionKnowledgeBases(session.session_id, knowledge);
      await worldbookApi.updateSessionWorldbooks(session.session_id, books);
      await useWorkbenchStore.getState().reloadSessions();
      onClose();
    } catch (e) { setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e)); } finally { setBusy(false); }
  }

  return <AppModal open title={t('sessionSettings')} closeLabel={t('close')} width="large" onClose={() => { if (!busy) onClose(); }}>
    {error ? <p role="alert" className="model-feedback error-text">{error}</p> : null}
    {error && loading ? <IconButton label={t('refresh')} onClick={() => setReload((value) => value + 1)}><RefreshCw size={16} /></IconButton> : null}
    {loading ? <p className="model-empty">{t('loading')}</p> : <form onSubmit={(e) => { e.preventDefault(); void save(); }}>
      <div className="model-tabs" role="tablist" aria-label={t('sessionSections')}>{(['members', 'configuration', 'knowledge', 'worldbook'] as Tab[]).map((key) => <button type="button" key={key} role="tab" aria-selected={tab === key} onClick={() => setTab(key)}>{t(key)}</button>)}</div>
      <fieldset className="model-form" disabled={busy}>
        {tab === 'members' ? <>
          <Field label={t('sessionTitle')}><input maxLength={120} value={draft.title} onChange={(e) => patch({ title: e.target.value })} /></Field>
          <Field label={t('conversationMode')}><select value={draft.context_mode} onChange={(e) => patch({ context_mode: e.target.value as Session['context_mode'] })}><option value="single_assistant">{t('single')}</option><option value="group_transcript">{t('group')}</option></select></Field>
          <Field label={t('currentSpeaker')}><select value={draft.current_persona_id} onChange={(e) => patch({ current_persona_id: e.target.value })}>{draft.personas.filter((p) => p.enabled).map((p) => <option value={p.persona_id} key={p.persona_id}>{p.name}</option>)}</select></Field>
          <div className="session-member-list">{draft.personas.map((member, index) => <div className="session-member-row" key={member.persona_id}>
            <PersonaAvatar name={member.name} attachmentId={member.avatar_attachment_id} />
            <Check label={member.name} checked={member.enabled} disabled={member.persona_id === draft.current_persona_id} onChange={(enabled) => changeMember(member.persona_id, { enabled })} />
            <div className="model-actions">
              <IconButton label={t('moveUp')} disabled={index === 0} onClick={() => move(index, -1)}><ArrowUp size={14} /></IconButton>
              <IconButton label={t('moveDown')} disabled={index === draft.personas.length - 1} onClick={() => move(index, 1)}><ArrowDown size={14} /></IconButton>
              <IconButton label={t('removeMember')} disabled={member.persona_id === draft.current_persona_id} onClick={() => patch({ personas: draft.personas.filter((m) => m.persona_id !== member.persona_id) })}><Trash2 size={14} /></IconButton>
            </div>
          </div>)}</div>
          <div className="persona-add-member"><Field label={t('addMember')}><select value={memberId} onChange={(e) => setMemberId(e.target.value)}><option value="">{t('selectPersona')}</option>{available.map((p) => <option value={p.id} key={p.id}>{p.name}</option>)}</select></Field><IconButton label={t('addMember')} disabled={!available.some((p) => p.id === memberId)} onClick={() => { const p = available.find((item) => item.id === memberId); if (p) patch({ personas: [...draft.personas, { persona_id: p.id, name: p.name, enabled: true, avatar_attachment_id: p.avatar_attachment_id }] }); setMemberId(''); }}><Plus size={17} /></IconButton></div>
          <button type="button" className="secondary-button" onClick={onManagePersonas}>{t('manage')}</button>
        </> : null}
        {tab === 'configuration' ? <>
          <ModelField profiles={profiles} value={draft.model_profile_id} onChange={(model_profile_id) => patch({ model_profile_id })} />
          <h3>{t('context')}</h3>
          <ContextFields value={draft.context_policy} onChange={(context_policy) => patch({ context_policy })} />
          <h3>{t('generation')}</h3>
          <GenerationFields value={draft.generation} onChange={(generation) => patch({ generation })} />
          <h3>{t('harness')}</h3>
          <Check label={t('harnessEnabled')} checked={draft.harness_enabled} onChange={(harness_enabled) => patch({ harness_enabled })} />
          {draft.harness_enabled ? <ToolsField tools={tools} value={draft.tools_allowed} onChange={(tools_allowed) => patch({ tools_allowed })} /> : null}
        </> : null}
        {tab === 'knowledge' ? <SessionBindings key={draft.current_persona_id} personaId={draft.current_persona_id} kind="knowledge" items={bases} ids={knowledge} onChange={setKnowledge} /> : null}
        {tab === 'worldbook' ? <SessionBindings key={draft.current_persona_id} personaId={draft.current_persona_id} kind="worldbook" items={worldbooks} ids={books} onChange={setBooks} /> : null}
        <div className="model-form-footer"><button type="submit" className="primary-button"><Save size={16} />{t('save')}</button></div>
      </fieldset>
    </form>}
  </AppModal>;
}

export function SessionBindings({ personaId, kind, items, ids, onChange }: { personaId: string; kind: 'knowledge' | 'worldbook'; items: Array<{ id: string; name: string; enabled: boolean }>; ids: string[]; onChange: (ids: string[]) => void }) {
  const { t } = useTranslation('personas');
  const [personaIds, setPersonaIds] = useState<string[] | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let live = true; setPersonaIds(null); setError('');
    const load = async () => kind === 'knowledge' ? (await chatApi.getPersonaKnowledge(personaId)).knowledge_base_ids : (await chatApi.getPersonaWorldbooks(personaId)).worldbook_ids;
    void load().then((values) => { if (live) setPersonaIds(values); }).catch((e) => { if (live) setError(String(e)); });
    return () => { live = false; };
  }, [personaId, kind, reload]);
  if (error) return <><p role="alert" className="error-text">{error}</p><IconButton label={t('refresh')} onClick={() => setReload((value) => value + 1)}><RefreshCw size={16} /></IconButton></>;
  if (personaIds === null) return <p className="model-empty">{t('loading')}</p>;
  return <>
    <h3 className="binding-section-heading"><LockKeyhole size={15} aria-hidden="true" />{t('personaBindings')}</h3>
    {personaIds.length ? <BindingsField items={items.filter((item) => personaIds.includes(item.id))} ids={personaIds} onChange={() => undefined} disabled /> : <p className="model-empty">{t('noBindings')}</p>}
    <h3>{t('sessionAdditions')}</h3>
    <BindingsField items={items.filter((item) => !personaIds.includes(item.id) || ids.includes(item.id))} ids={ids} onChange={onChange} />
  </>;
}
