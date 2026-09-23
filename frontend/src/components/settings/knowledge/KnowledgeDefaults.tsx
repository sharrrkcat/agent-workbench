import { Switch } from '@/components/ui/switch';
import { FieldGroup, Field, FieldLabel, FieldSet } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { Button } from '@/components/ui/button';
import { useEffect, useState } from 'react';
import { Save } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { knowledgeApi } from '../../../api/knowledge';
import { useModelsStore } from '../../../store/useModelsStore';
import type { KnowledgeSettings, KnowledgeSettingsInput } from '../../../types/knowledge';

import { equalDraft, errorText, Feedback, ResourceLoading, useResourceTask } from '../resources/ResourceUI';
import { KnowledgeModelSelect } from './KnowledgeModelSelect';

export function knowledgeSettingsInput(value: KnowledgeSettings): KnowledgeSettingsInput {
  const { id: _id, ...input } = value;
  return input;
}

export function KnowledgeDefaults({
  onState,
}: {
  onState: (value: { dirty: boolean; busy: boolean }) => void;
}) {
  const { t } = useTranslation('knowledge');
  const models = useModelsStore((state) => state.profiles);
  const [draft, setDraft] = useState<KnowledgeSettingsInput | null>(null);
  const [baseline, setBaseline] = useState<KnowledgeSettingsInput | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const task = useResourceTask();
  const dirty = !equalDraft(draft, baseline);
  useEffect(() => {
    onState({ dirty, busy: !!task.busy });
  }, [dirty, task.busy, onState]);
  useEffect(() => {
    let live = true;
    setError('');
    void knowledgeApi
      .getKnowledgeSettings()
      .then((value) => {
        if (live) {
          setDraft(knowledgeSettingsInput(value));
          setBaseline(knowledgeSettingsInput(value));
        }
      })
      .catch((reason) => {
        if (live) setError(errorText(reason));
      });
    return () => {
      live = false;
    };
  }, [reload]);
  if (!draft) return <ResourceLoading error={error} retry={() => setReload((value) => value + 1)} />;
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void task.run(
          'save',
          async () => {
            const value = knowledgeSettingsInput(await knowledgeApi.updateKnowledgeSettings(draft));
            setDraft(value);
            setBaseline(value);
          },
          t('saved'),
        );
      }}
    >
      <Feedback {...task} />
      <FieldSet className="resource-fieldset" disabled={!!task.busy}>
        <Field orientation="horizontal">
          <Switch
            checked={draft.hybrid_search_enabled}
            onCheckedChange={(value) => setDraft({ ...draft, hybrid_search_enabled: value })}
          />
          <FieldLabel>{t('hybrid')}</FieldLabel>
        </Field>
        <Field orientation="horizontal">
          <Switch
            checked={draft.reranker_enabled}
            onCheckedChange={(value) => setDraft({ ...draft, reranker_enabled: value })}
          />
          <FieldLabel>{t('reranker')}</FieldLabel>
        </Field>
        <KnowledgeModelSelect
          kind="reranker"
          value={draft.reranker_model_profile_id}
          models={models}
          optional
          onChange={(value) => setDraft({ ...draft, reranker_model_profile_id: value })}
        />
        <FieldGroup className="grid gap-4 sm:grid-cols-2">
          {(
            [
              ['default_chunk_size', 'chunkSize', 100, 10000],
              ['default_chunk_overlap', 'chunkOverlap', 0, 5000],
              ['default_final_top_k', 'finalResults', 1, 100],
            ] as const
          ).map(([key, label, min, max]) => (
            <Field key={key}>
              <FieldLabel>{t(label)}</FieldLabel>
              <Input
                type="number"
                min={min}
                max={max}
                step={1}
                required
                value={Number.isNaN(draft[key]) ? '' : (draft[key] ?? '')}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    [key]: event.currentTarget.value === '' ? Number.NaN : Number(event.currentTarget.value),
                  })
                }
              />
            </Field>
          ))}
        </FieldGroup>
        <Collapsible className="resource-advanced">
          <CollapsibleTrigger render={<Button type="button" variant="ghost" className="justify-start" />}>
            {t('settings:resources.advanced')}
          </CollapsibleTrigger>
          <CollapsibleContent keepMounted>
            <h3>{t('retrieval')}</h3>
            <FieldGroup className="grid gap-4 sm:grid-cols-2">
              {(
                [
                  ['default_vector_candidate_k', 'vectorCandidates', 1, 1000],
                  ['default_keyword_candidate_k', 'keywordCandidates', 1, 1000],
                  ['reranker_candidate_limit', 'rerankerCandidates', 1, 1000],
                  ['rrf_k', 'rrfConstant', 1, 1000],
                  ['default_max_context_chars', 'contextLimit', 100, 200000],
                ] as const
              ).map(([key, label, min, max]) => (
                <Field key={key}>
                  <FieldLabel>{t(label)}</FieldLabel>
                  <Input
                    type="number"
                    min={min}
                    max={max}
                    step={1}
                    required
                    value={Number.isNaN(draft[key]) ? '' : (draft[key] ?? '')}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        [key]:
                          event.currentTarget.value === '' ? Number.NaN : Number(event.currentTarget.value),
                      })
                    }
                  />
                </Field>
              ))}
              <Field>
                <FieldLabel>{t('minScore')}</FieldLabel>
                <Input
                  type="number"
                  min={-1}
                  max={1}
                  step={0.01}
                  value={Number.isNaN(draft.min_score_threshold) ? '' : (draft.min_score_threshold ?? '')}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      min_score_threshold:
                        event.currentTarget.value === '' ? null : Number(event.currentTarget.value),
                    })
                  }
                />
              </Field>
              <Field>
                <FieldLabel>{t('defaultMinScore')}</FieldLabel>
                <Input
                  type="number"
                  min={-1}
                  max={1}
                  step={0.01}
                  value={Number.isNaN(draft.default_min_score) ? '' : (draft.default_min_score ?? '')}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      default_min_score:
                        event.currentTarget.value === '' ? null : Number(event.currentTarget.value),
                    })
                  }
                />
              </Field>
              <Field>
                <FieldLabel>{t('chunksPerSource')}</FieldLabel>
                <Input
                  type="number"
                  min={1}
                  max={100}
                  step={1}
                  value={
                    Number.isNaN(draft.retrieval_max_chunks_per_source)
                      ? ''
                      : (draft.retrieval_max_chunks_per_source ?? '')
                  }
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      retrieval_max_chunks_per_source:
                        event.currentTarget.value === '' ? null : Number(event.currentTarget.value),
                    })
                  }
                />
              </Field>
              <Field>
                <FieldLabel>{t('chunksPerBase')}</FieldLabel>
                <Input
                  type="number"
                  min={1}
                  max={100}
                  step={1}
                  value={
                    Number.isNaN(draft.retrieval_max_chunks_per_knowledge_base)
                      ? ''
                      : (draft.retrieval_max_chunks_per_knowledge_base ?? '')
                  }
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      retrieval_max_chunks_per_knowledge_base:
                        event.currentTarget.value === '' ? null : Number(event.currentTarget.value),
                    })
                  }
                />
              </Field>
            </FieldGroup>
            <p className="resource-hint">{t('scorePrecedence')}</p>
            <h3>{t('sourceLimits')}</h3>
            <FieldGroup className="grid gap-4 sm:grid-cols-2">
              {(
                [
                  ['max_source_size_bytes', 'sourceSizeLimit', 1024, 104857600],
                  ['max_chunks_per_source', 'sourceChunksLimit', 1, 100000],
                  ['max_total_index_chars_per_source', 'sourceCharsLimit', 1000, 10000000],
                ] as const
              ).map(([key, label, min, max]) => (
                <Field key={key}>
                  <FieldLabel>{t(label)}</FieldLabel>
                  <Input
                    type="number"
                    min={min}
                    max={max}
                    step={1}
                    required
                    value={Number.isNaN(draft[key]) ? '' : (draft[key] ?? '')}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        [key]:
                          event.currentTarget.value === '' ? Number.NaN : Number(event.currentTarget.value),
                      })
                    }
                  />
                </Field>
              ))}
            </FieldGroup>
            <h3>{t('context')}</h3>
            <Field>
              <FieldLabel>{t('contextInstruction')}</FieldLabel>
              <Textarea
                rows={5}
                required
                value={draft.knowledge_context_instruction}
                onChange={(event) =>
                  setDraft({ ...draft, knowledge_context_instruction: event.target.value })
                }
              ></Textarea>
            </Field>
            <Field>
              <FieldLabel>{t('snippetTemplate')}</FieldLabel>
              <Textarea
                rows={7}
                required
                value={draft.knowledge_context_snippet_template}
                onChange={(event) =>
                  setDraft({ ...draft, knowledge_context_snippet_template: event.target.value })
                }
              ></Textarea>
            </Field>
          </CollapsibleContent>
        </Collapsible>
        <div className="resource-form-footer">
          <Button type="submit" disabled={!dirty} variant="default">
            <Save size={16} />
            {t('common:save')}
          </Button>
        </div>
      </FieldSet>
    </form>
  );
}
