import { ArrowDown, ArrowUp, Plus, Save, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { knowledgeApi } from '../../api/knowledge';
import { worldbookApi } from '../../api/worldbook';
import { chatApi } from '../../api/chat';
import { ApiError } from '../../api/http';
import { useModelsStore } from '../../store/useModelsStore';
import { usePersonasStore } from '../../store/usePersonasStore';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { BindingMode, Session, SessionPatch, SessionPersona } from '../../types/chat';
import type { KnowledgeBase } from '../../types/knowledge';
import type { Worldbook } from '../../types/worldbook';
import { AppModal } from '../ui/AppModal';
import { BindingsField, Check, ContextFields, Field, GenerationFields, IconButton, ModelField, PersonaAvatar, ToolsField } from './ConfigurationFields';

type Tab = 'members' | 'overrides' | 'knowledge' | 'worldbook';

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
  const [memberId, setMemberId] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true;
    void Promise.all([usePersonasStore.getState().reload(), knowledgeApi.listSessionKnowledgeBases(session.session_id), worldbookApi.getSessionWorldbooks(session.session_id), knowledgeApi.listKnowledgeBases(), worldbookApi.listWorldbooks()])
      .then(([, kb, wb, bases, worldbooks]) => { if (live) { setKnowledge(kb.knowledge_base_ids); setBooks(wb.worldbook_ids); setBases(bases); setWorldbooks(worldbooks); setLoading(false); } })
      .catch((e) => { if (live) setError(String(e)); });
    return () => { live = false; };
  }, [session.session_id]);
  const patch = (values: Partial<Session>) => setDraft((current) => ({ ...current, ...values }));
  const available = personas.filter((p) => !draft.personas.some((m) => m.persona_id === p.id));
  const selected = personas.find((p) => p.id === draft.current_persona_id);
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
      tools_allowed: draft.tools_allowed?.map((s) => s.trim()).filter(Boolean) ?? null,
    };
    try {
      await chatApi.updateSession(session.session_id, values);
      await knowledgeApi.updateSessionKnowledgeBases(session.session_id, draft.knowledge_binding_mode, knowledge);
      await worldbookApi.updateSessionWorldbooks(session.session_id, draft.worldbook_binding_mode, books);
      await useWorkbenchStore.getState().reloadSessions();
      onClose();
    } catch (e) { setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e)); } finally { setBusy(false); }
  }

  return <AppModal open title={t('sessionSettings')} closeLabel={t('close')} width="large" onClose={() => { if (!busy) onClose(); }}>
    {error ? <p role="alert" className="model-feedback error-text">{error}</p> : null}
    {loading ? <p className="model-empty">{t('loading')}</p> : <form onSubmit={(e) => { e.preventDefault(); void save(); }}>
      <div className="model-tabs" role="tablist" aria-label={t('sessionSections')}>{(['members', 'overrides', 'knowledge', 'worldbook'] as Tab[]).map((key) => <button type="button" key={key} role="tab" aria-selected={tab === key} onClick={() => setTab(key)}>{t(key)}</button>)}</div>
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
        {tab === 'overrides' ? <>
          <ModelField profiles={profiles} value={draft.model_profile_id} inheritLabel={t('inheritPersona')} onChange={(model_profile_id) => patch({ model_profile_id })} />
          <h3>{t('context')}</h3><Check label={t('overrideContext')} checked={draft.context_policy !== null} onChange={(enabled) => patch({ context_policy: enabled ? structuredClone(selected?.context_policy || session.effective.context_policy) : null })} />
          {draft.context_policy ? <ContextFields value={draft.context_policy} onChange={(context_policy) => patch({ context_policy })} /> : <span className="configuration-state">{t('contextModes.' + (selected?.context_policy.mode || session.effective.context_policy.mode))}</span>}
          <h3>{t('generation')}</h3><Check label={t('overrideGeneration')} checked={draft.generation !== null} onChange={(enabled) => patch({ generation: enabled ? { ...(selected?.generation || {}) } : null })} />
          {draft.generation ? <GenerationFields value={draft.generation} onChange={(generation) => patch({ generation })} /> : null}
          <h3>{t('harness')}</h3><p className="configuration-state">{t('harnessHelp')}</p>
          <Check label={t('overrideHarness')} checked={draft.harness_enabled !== null} onChange={(enabled) => patch({ harness_enabled: enabled ? selected?.harness_enabled || false : null })} />
          {draft.harness_enabled !== null ? <Check label={t('harnessEnabled')} checked={draft.harness_enabled} onChange={(harness_enabled) => patch({ harness_enabled })} /> : null}
          <Check label={t('overrideTools')} checked={draft.tools_allowed !== null} onChange={(enabled) => patch({ tools_allowed: enabled ? [...(selected?.tools_allowed || [])] : null })} />
          {draft.tools_allowed !== null ? <ToolsField value={draft.tools_allowed} onChange={(tools_allowed) => patch({ tools_allowed })} /> : null}
        </> : null}
        {tab === 'knowledge' ? <>
          <BindingModeField value={draft.knowledge_binding_mode} onChange={(knowledge_binding_mode) => patch({ knowledge_binding_mode })} />
          {draft.knowledge_binding_mode === 'override' ? <BindingsField items={bases} ids={knowledge} onChange={setKnowledge} /> : <InheritedBindings personaId={draft.current_persona_id} kind="knowledge" items={bases} />}
        </> : null}
        {tab === 'worldbook' ? <>
          <BindingModeField value={draft.worldbook_binding_mode} onChange={(worldbook_binding_mode) => patch({ worldbook_binding_mode })} />
          {draft.worldbook_binding_mode === 'override' ? <BindingsField items={worldbooks} ids={books} onChange={setBooks} /> : <InheritedBindings personaId={draft.current_persona_id} kind="worldbook" items={worldbooks} />}
        </> : null}
        <div className="model-form-footer"><button type="submit" className="primary-button"><Save size={16} />{t('save')}</button></div>
      </fieldset>
    </form>}
  </AppModal>;
}

function BindingModeField({ value, onChange }: { value: BindingMode; onChange: (mode: BindingMode) => void }) {
  const { t } = useTranslation('personas');
  return <Field label={t('bindingsMode')}><select value={value} onChange={(e) => onChange(e.target.value as BindingMode)}><option value="inherit">{t('inheritPersona')}</option><option value="override">{t('sessionOverride')}</option></select></Field>;
}

function InheritedBindings({ personaId, kind, items }: { personaId: string; kind: 'knowledge' | 'worldbook'; items: Array<{ id: string; name: string; enabled: boolean }> }) {
  const { t } = useTranslation('personas');
  const [ids, setIds] = useState<string[] | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let live = true; setIds(null); setError('');
    const load = async () => kind === 'knowledge' ? (await chatApi.getPersonaKnowledge(personaId)).knowledge_base_ids : (await chatApi.getPersonaWorldbooks(personaId)).worldbook_ids;
    void load().then((values) => { if (live) setIds(values); }).catch((e) => { if (live) setError(String(e)); });
    return () => { live = false; };
  }, [personaId, kind]);
  if (error) return <p role="alert" className="error-text">{error}</p>;
  if (ids === null) return <p className="model-empty">{t('loading')}</p>;
  if (!ids.length) return <p className="model-empty">{t('noBindings')}</p>;
  return <BindingsField items={items.filter((item) => ids.includes(item.id))} ids={ids} onChange={() => undefined} disabled />;
}
