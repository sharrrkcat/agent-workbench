import { useEffect, useState } from 'react';
import { Save } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { knowledgeApi } from '../../../api/knowledge';
import { useModelsStore } from '../../../store/useModelsStore';
import type { KnowledgeSettings, KnowledgeSettingsInput } from '../../../types/knowledge';
import { ToggleSwitch } from '../../ui/ToggleSwitch';
import { equalDraft, errorText, Feedback, Field, NumberInput, ResourceLoading, useResourceTask } from '../resources/ResourceUI';
import { KnowledgeModelSelect } from './KnowledgeModelSelect';

export function knowledgeSettingsInput(value: KnowledgeSettings): KnowledgeSettingsInput {
  const { id: _id, ...input } = value;
  return input;
}

export function KnowledgeDefaults({ onState }: { onState: (value: { dirty: boolean; busy: boolean }) => void }) {
  const { t } = useTranslation('knowledge');
  const models = useModelsStore((state) => state.profiles);
  const [draft, setDraft] = useState<KnowledgeSettingsInput | null>(null);
  const [baseline, setBaseline] = useState<KnowledgeSettingsInput | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const task = useResourceTask();
  const dirty = !equalDraft(draft, baseline);
  useEffect(() => { onState({ dirty, busy: !!task.busy }); }, [dirty, task.busy, onState]);
  useEffect(() => {
    let live = true; setError('');
    void knowledgeApi.getKnowledgeSettings().then((value) => { if (live) { setDraft(knowledgeSettingsInput(value)); setBaseline(knowledgeSettingsInput(value)); } })
      .catch((reason) => { if (live) setError(errorText(reason)); });
    return () => { live = false; };
  }, [reload]);
  if (!draft) return <ResourceLoading error={error} retry={() => setReload((value) => value + 1)} />;
  return <form onSubmit={(event) => { event.preventDefault(); void task.run('save', async () => {
    const value = knowledgeSettingsInput(await knowledgeApi.updateKnowledgeSettings(draft)); setDraft(value); setBaseline(value);
  }, t('saved')); }}>
    <Feedback {...task} /><fieldset className="resource-fieldset" disabled={!!task.busy}>
      <ToggleSwitch checked={draft.hybrid_search_enabled} label={t('hybrid')} onChange={(value) => setDraft({ ...draft, hybrid_search_enabled: value })} />
      <ToggleSwitch checked={draft.reranker_enabled} label={t('reranker')} onChange={(value) => setDraft({ ...draft, reranker_enabled: value })} />
      <KnowledgeModelSelect kind="reranker" value={draft.reranker_model_profile_id} models={models} optional onChange={(value) => setDraft({ ...draft, reranker_model_profile_id: value })} />
      <div className="resource-form-grid">{([
        ['default_chunk_size', 'chunkSize', 100, 10000], ['default_chunk_overlap', 'chunkOverlap', 0, 5000], ['default_final_top_k', 'finalResults', 1, 100],
      ] as const).map(([key, label, min, max]) => <NumberInput key={key} label={t(label)} min={min} max={max} value={draft[key]} onChange={(value) => setDraft({ ...draft, [key]: value ?? min })} />)}</div>
      <details className="resource-advanced"><summary>{t('settings:resources.advanced')}</summary>
        <h3>{t('retrieval')}</h3><div className="resource-form-grid">{([
          ['default_vector_candidate_k', 'vectorCandidates', 1, 1000], ['default_keyword_candidate_k', 'keywordCandidates', 1, 1000],
          ['reranker_candidate_limit', 'rerankerCandidates', 1, 1000], ['rrf_k', 'rrfConstant', 1, 1000], ['default_max_context_chars', 'contextLimit', 100, 200000],
        ] as const).map(([key, label, min, max]) => <NumberInput key={key} label={t(label)} min={min} max={max} value={draft[key]} onChange={(value) => setDraft({ ...draft, [key]: value ?? min })} />)}
          <NumberInput label={t('minScore')} optional min={-1} max={1} step={0.01} value={draft.min_score_threshold} onChange={(value) => setDraft({ ...draft, min_score_threshold: value })} />
          <NumberInput label={t('defaultMinScore')} optional min={-1} max={1} step={0.01} value={draft.default_min_score} onChange={(value) => setDraft({ ...draft, default_min_score: value })} />
          <NumberInput label={t('chunksPerSource')} optional min={1} max={100} value={draft.retrieval_max_chunks_per_source} onChange={(value) => setDraft({ ...draft, retrieval_max_chunks_per_source: value })} />
          <NumberInput label={t('chunksPerBase')} optional min={1} max={100} value={draft.retrieval_max_chunks_per_knowledge_base} onChange={(value) => setDraft({ ...draft, retrieval_max_chunks_per_knowledge_base: value })} />
        </div><p className="resource-hint">{t('scorePrecedence')}</p>
        <h3>{t('sourceLimits')}</h3><div className="resource-form-grid">{([
          ['max_source_size_bytes', 'sourceSizeLimit', 1024, 104857600], ['max_chunks_per_source', 'sourceChunksLimit', 1, 100000],
          ['max_total_index_chars_per_source', 'sourceCharsLimit', 1000, 10000000],
        ] as const).map(([key, label, min, max]) => <NumberInput key={key} label={t(label)} min={min} max={max} value={draft[key]} onChange={(value) => setDraft({ ...draft, [key]: value ?? min })} />)}</div>
        <h3>{t('context')}</h3>
        <Field label={t('contextInstruction')}><textarea rows={5} required value={draft.knowledge_context_instruction} onChange={(event) => setDraft({ ...draft, knowledge_context_instruction: event.target.value })} /></Field>
        <Field label={t('snippetTemplate')}><textarea rows={7} required value={draft.knowledge_context_snippet_template} onChange={(event) => setDraft({ ...draft, knowledge_context_snippet_template: event.target.value })} /></Field>
      </details>
      <div className="resource-form-footer"><button type="submit" className="primary-button" disabled={!dirty}><Save size={16} />{t('common:save')}</button></div>
    </fieldset>
  </form>;
}
