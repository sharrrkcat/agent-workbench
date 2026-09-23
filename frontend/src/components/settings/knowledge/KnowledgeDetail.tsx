import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Input } from '@/components/ui/input';
import { FieldGroup, Field, FieldLabel, FieldSet } from '@/components/ui/field';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, Save, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { KnowledgeBase, KnowledgeBaseInput } from '../../../types/knowledge';
import { knowledgeApi } from '../../../api/knowledge';
import { useModelsStore } from '../../../store/useModelsStore';

import { equalDraft, errorText, Feedback, ResourceLoading, useResourceTask } from '../resources/ResourceUI';
import { KnowledgeModelSelect } from './KnowledgeModelSelect';
import { KnowledgeSearch } from './KnowledgeSearch';
import { KnowledgeSources } from './KnowledgeSources';

export function knowledgeBaseInput(value?: KnowledgeBaseInput): KnowledgeBaseInput {
  return {
    name: value?.name ?? '',
    description: value?.description ?? '',
    embedding_model_profile_id: value?.embedding_model_profile_id ?? '',
    enabled: value?.enabled ?? true,
    aliases_text: value?.aliases_text ?? '',
    vector_candidate_k_override: value?.vector_candidate_k_override ?? null,
    keyword_candidate_k_override: value?.keyword_candidate_k_override ?? null,
    final_top_k_override: value?.final_top_k_override ?? null,
    max_context_chars_override: value?.max_context_chars_override ?? null,
  };
}

export function KnowledgeDetail({
  id,
  onBack,
  onSaved,
  onDeleted,
  onState,
}: {
  id: string;
  onBack: () => void;
  onSaved: (base: KnowledgeBase, created: boolean) => void;
  onDeleted: () => void;
  onState: (value: { dirty: boolean; busy: boolean }) => void;
}) {
  const { confirm, confirmation } = useConfirmDialog();
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
  const dirty = !equalDraft(draft, baseline),
    locked = !!task.busy || sourcesState.busy;
  useEffect(() => {
    onState({ dirty: dirty || sourcesState.dirty, busy: locked });
  }, [dirty, sourcesState.dirty, locked, onState]);
  useEffect(() => {
    if (id === 'new') return;
    let live = true;
    setLoading(true);
    setLoadError('');
    void knowledgeApi
      .getKnowledgeBase(id)
      .then((value) => {
        if (live) {
          setBase(value);
          setDraft(knowledgeBaseInput(value));
          setBaseline(knowledgeBaseInput(value));
          setLoading(false);
        }
      })
      .catch((reason) => {
        if (live) {
          setLoadError(errorText(reason));
          setLoading(false);
        }
      });
    return () => {
      live = false;
    };
  }, [id, reload]);
  const onBase = useCallback(
    (value: KnowledgeBase) => {
      setBase(value);
      onSaved(value, false);
    },
    [onSaved],
  );
  if (loading || loadError)
    return (
      <>
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={t('common:back')}
                onClick={onBack}
              />
            }
          >
            <ArrowLeft size={18} />
          </TooltipTrigger>
          <TooltipContent>{t('common:back')}</TooltipContent>
        </Tooltip>
        <ResourceLoading error={loadError} retry={() => setReload((value) => value + 1)} />
      </>
    );
  return (
    <Tabs value={tab} onValueChange={setTab}>
      <div className="resource-heading">
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={t('common:back')}
                disabled={locked}
                onClick={onBack}
              />
            }
          >
            <ArrowLeft size={18} />
          </TooltipTrigger>
          <TooltipContent>{t('common:back')}</TooltipContent>
        </Tooltip>
        <h2>{base?.name || t('newBase')}</h2>
        {base ? (
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  type="button"
                  variant="destructive"
                  size="icon"
                  aria-label={t('common:delete')}
                  disabled={locked}
                  onClick={async () => {
                    if (await confirm(t('deleteBaseConfirm', { name: base.name }), { destructive: true }))
                      void task.run('delete', async () => {
                        await knowledgeApi.deleteKnowledgeBase(base.id);
                        onDeleted();
                      });
                  }}
                />
              }
            >
              <Trash2 size={16} />
            </TooltipTrigger>
            <TooltipContent>{t('common:delete')}</TooltipContent>
          </Tooltip>
        ) : null}
      </div>
      {base ? (
        <div className="resource-meta">
          <span className={`resource-badge ${base.index_status === 'ready' ? 'active' : 'warning'}`}>
            {t('statuses.' + base.index_status)}
          </span>
          <span>
            {models.find((model) => model.id === base.embedding_model_profile_id)?.name || t('missingModel')}
          </span>
        </div>
      ) : null}
      {base?.index_status === 'needs_reindex' ? (
        <p className="resource-warning">{t('needsReindex')}</p>
      ) : null}
      <TabsList aria-label={t('settings:resources.sections')}>
        {[
          { id: 'config', label: t('config') },
          { id: 'sources', label: t('sources'), disabled: !base },
          { id: 'search', label: t('searchTest'), disabled: !base },
        ].map((item) => (
          <TabsTrigger key={item.id} value={item.id} disabled={'disabled' in item && !!item.disabled}>
            {item.label}
          </TabsTrigger>
        ))}
      </TabsList>
      <Feedback {...task} />
      <TabsContent value="config" keepMounted hidden={tab !== 'config'}>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void task.run(
              'save',
              async () => {
                const saved = base
                  ? await knowledgeApi.patchKnowledgeBase(base.id, draft)
                  : await knowledgeApi.createKnowledgeBase(draft);
                setBase(saved);
                setDraft(knowledgeBaseInput(saved));
                setBaseline(knowledgeBaseInput(saved));
                setRevision((value) => value + 1);
                onSaved(saved, !base);
              },
              t('saved'),
            );
          }}
        >
          <FieldSet className="resource-fieldset" disabled={locked}>
            <FieldGroup className="grid gap-4 sm:grid-cols-2">
              <Field>
                <FieldLabel>{t('baseName')}</FieldLabel>
                <Input
                  required
                  value={draft.name}
                  onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                />
              </Field>
              <KnowledgeModelSelect
                kind="embedding"
                value={draft.embedding_model_profile_id}
                models={models}
                onChange={(value) => setDraft({ ...draft, embedding_model_profile_id: value || '' })}
              />
            </FieldGroup>
            <Field>
              <FieldLabel>{t('description')}</FieldLabel>
              <Textarea
                rows={4}
                value={draft.description}
                onChange={(event) => setDraft({ ...draft, description: event.target.value })}
              ></Textarea>
            </Field>
            <Field orientation="horizontal">
              <Switch
                checked={draft.enabled ?? true}
                onCheckedChange={(enabled) => setDraft({ ...draft, enabled })}
              />
              <FieldLabel>{t('enabled')}</FieldLabel>
            </Field>
            <Collapsible className="resource-advanced">
              <CollapsibleTrigger render={<Button type="button" variant="ghost" className="justify-start" />}>
                {t('settings:resources.advanced')}
              </CollapsibleTrigger>
              <CollapsibleContent keepMounted>
                <Field>
                  <FieldLabel>{t('aliases')}</FieldLabel>
                  <Input
                    value={draft.aliases_text}
                    onChange={(event) => setDraft({ ...draft, aliases_text: event.target.value })}
                  />
                </Field>
                <FieldGroup className="grid gap-4 sm:grid-cols-2">
                  {(
                    [
                      ['vector_candidate_k_override', 'vectorCandidates', 1, 1000],
                      ['keyword_candidate_k_override', 'keywordCandidates', 1, 1000],
                      ['final_top_k_override', 'finalResults', 1, 100],
                      ['max_context_chars_override', 'contextLimit', 100, 200000],
                    ] as const
                  ).map(([key, label, min, max]) => (
                    <Field key={key}>
                      <FieldLabel>{t('overrideLabel', { label: t(label) })}</FieldLabel>
                      <Input
                        type="number"
                        min={min}
                        max={max}
                        step={1}
                        value={draft[key] ?? ''}
                        onChange={(event) =>
                          setDraft({
                            ...draft,
                            [key]:
                              event.currentTarget.value === '' ? null : Number(event.currentTarget.value),
                          })
                        }
                      />
                    </Field>
                  ))}
                </FieldGroup>
              </CollapsibleContent>
            </Collapsible>
            <div className="resource-form-footer">
              <Button
                type="submit"
                disabled={!draft.name.trim() || !draft.embedding_model_profile_id || (!!base && !dirty)}
                variant="default"
              >
                <Save size={16} />
                {t('common:save')}
              </Button>
            </div>
          </FieldSet>
        </form>
      </TabsContent>
      {base ? (
        <>
          <TabsContent value="sources" keepMounted hidden={tab !== 'sources'}>
            <KnowledgeSources
              baseId={base.id}
              revision={revision}
              onBase={onBase}
              onState={setSourcesState}
            />
          </TabsContent>
          <TabsContent value="search" keepMounted hidden={tab !== 'search'}>
            <KnowledgeSearch baseId={base.id} />
          </TabsContent>
        </>
      ) : null}
      {confirmation}
    </Tabs>
  );
}
