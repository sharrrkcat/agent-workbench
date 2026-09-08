import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, Save, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { KnowledgeBase, KnowledgeBaseInput } from '../../../types/knowledge';
import { knowledgeApi } from '../../../api/knowledge';
import { useModelsStore } from '../../../store/useModelsStore';
import { ToggleSwitch } from '../../ui/ToggleSwitch';
import { equalDraft, errorText, Feedback, Field, NumberInput, ResourceIcon, ResourceLoading, ResourceTabs, useResourceTask } from '../resources/ResourceUI';
import { KnowledgeModelSelect } from './KnowledgeModelSelect';
import { KnowledgeSearch } from './KnowledgeSearch';
import { KnowledgeSources } from './KnowledgeSources';

export function knowledgeBaseInput(value?: KnowledgeBaseInput): KnowledgeBaseInput {
  return { name: value?.name ?? '', description: value?.description ?? '', embedding_model_profile_id: value?.embedding_model_profile_id ?? '',
    enabled: value?.enabled ?? true, aliases_text: value?.aliases_text ?? '', vector_candidate_k_override: value?.vector_candidate_k_override ?? null,
    keyword_candidate_k_override: value?.keyword_candidate_k_override ?? null, final_top_k_override: value?.final_top_k_override ?? null,
    max_context_chars_override: value?.max_context_chars_override ?? null };
}

export function KnowledgeDetail({ id, onBack, onSaved, onDeleted, onState }: {
  id: string; onBack: () => void; onSaved: (base: KnowledgeBase, created: boolean) => void; onDeleted: () => void;
  onState: (value: { dirty: boolean; busy: boolean }) => void;
}) {
  const { t } = useTranslation('knowledge');
  const models = useModelsStore((state) => state.profiles);
  const [base, setBase] = useState<KnowledgeBase | null>(null);
  const [draft, setDraft] = useState(knowledgeBaseInput);
  const [baseline, setBaseline] = useState(knowledgeBaseInput);
  const [tab, setTab] = useState<'config' | 'sources' | 'search'>(id === 'new' ? 'config' : 'sources');
  const [loading, setLoading] = useState(id !== 'new');
  const [loadError, setLoadError] = useState('');
  const [reload, setReload] = useState(0);
  const [revision, setRevision] = useState(0);
  const [sourcesState, setSourcesState] = useState({ dirty: false, busy: false });
  const task = useResourceTask();
  const dirty = !equalDraft(draft, baseline), locked = !!task.busy || sourcesState.busy;
  useEffect(() => { onState({ dirty: dirty || sourcesState.dirty, busy: locked }); }, [dirty, sourcesState.dirty, locked, onState]);
  useEffect(() => {
    if (id === 'new') return;
    let live = true; setLoading(true); setLoadError('');
    void knowledgeApi.getKnowledgeBase(id).then((value) => { if (live) { setBase(value); setDraft(knowledgeBaseInput(value)); setBaseline(knowledgeBaseInput(value)); setLoading(false); } })
      .catch((reason) => { if (live) { setLoadError(errorText(reason)); setLoading(false); } });
    return () => { live = false; };
  }, [id, reload]);
  const onBase = useCallback((value: KnowledgeBase) => { setBase(value); onSaved(value, false); }, [onSaved]);
  if (loading || loadError) return <><ResourceIcon label={t('common:back')} onClick={onBack}><ArrowLeft size={18} /></ResourceIcon><ResourceLoading error={loadError} retry={() => setReload((value) => value + 1)} /></>;
  return <>
    <div className="resource-heading"><ResourceIcon label={t('common:back')} disabled={locked} onClick={onBack}><ArrowLeft size={18} /></ResourceIcon><h2>{base?.name || t('newBase')}</h2>
      {base ? <ResourceIcon label={t('common:delete')} disabled={locked} danger onClick={() => { if (window.confirm(t('deleteBaseConfirm', { name: base.name }))) void task.run('delete', async () => { await knowledgeApi.deleteKnowledgeBase(base.id); onDeleted(); }); }}><Trash2 size={16} /></ResourceIcon> : null}
    </div>
    {base ? <div className="resource-meta"><span className={`resource-badge ${base.index_status === 'ready' ? 'active' : 'warning'}`}>{t('statuses.' + base.index_status)}</span><span>{models.find((model) => model.id === base.embedding_model_profile_id)?.name || t('missingModel')}</span></div> : null}
    {base?.index_status === 'needs_reindex' ? <p className="resource-warning">{t('needsReindex')}</p> : null}
    <ResourceTabs value={tab} onChange={setTab} tabs={[{ id: 'config', label: t('config') }, { id: 'sources', label: t('sources'), disabled: !base }, { id: 'search', label: t('searchTest'), disabled: !base }]} />
    <Feedback {...task} />
    <div hidden={tab !== 'config'}><form onSubmit={(event) => { event.preventDefault(); void task.run('save', async () => {
      const saved = base ? await knowledgeApi.patchKnowledgeBase(base.id, draft) : await knowledgeApi.createKnowledgeBase(draft);
      setBase(saved); setDraft(knowledgeBaseInput(saved)); setBaseline(knowledgeBaseInput(saved)); setRevision((value) => value + 1); onSaved(saved, !base);
    }, t('saved')); }}><fieldset className="resource-fieldset" disabled={locked}>
      <div className="resource-form-grid"><Field label={t('baseName')}><input required value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></Field>
        <KnowledgeModelSelect kind="embedding" value={draft.embedding_model_profile_id} models={models} onChange={(value) => setDraft({ ...draft, embedding_model_profile_id: value || '' })} /></div>
      <Field label={t('description')}><textarea rows={4} value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></Field>
      <ToggleSwitch checked={draft.enabled ?? true} label={t('enabled')} onChange={(enabled) => setDraft({ ...draft, enabled })} />
      <details className="resource-advanced"><summary>{t('settings:resources.advanced')}</summary>
        <Field label={t('aliases')}><input value={draft.aliases_text} onChange={(event) => setDraft({ ...draft, aliases_text: event.target.value })} /></Field>
        <div className="resource-form-grid">{([
          ['vector_candidate_k_override', 'vectorCandidates', 1, 1000], ['keyword_candidate_k_override', 'keywordCandidates', 1, 1000],
          ['final_top_k_override', 'finalResults', 1, 100], ['max_context_chars_override', 'contextLimit', 100, 200000],
        ] as const).map(([key, label, min, max]) => <NumberInput key={key} label={t('overrideLabel', { label: t(label) })} optional min={min} max={max} value={draft[key] ?? null} onChange={(value) => setDraft({ ...draft, [key]: value })} />)}</div>
      </details>
      <div className="resource-form-footer"><button type="submit" className="primary-button" disabled={!draft.name.trim() || !draft.embedding_model_profile_id || (!!base && !dirty)}><Save size={16} />{t('common:save')}</button></div>
    </fieldset></form></div>
    {base ? <><div hidden={tab !== 'sources'}><KnowledgeSources baseId={base.id} revision={revision} onBase={onBase} onState={setSourcesState} /></div>
      <div hidden={tab !== 'search'}><KnowledgeSearch baseId={base.id} /></div></> : null}
  </>;
}
