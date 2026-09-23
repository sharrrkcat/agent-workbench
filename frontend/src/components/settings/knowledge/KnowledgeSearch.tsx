import { Input } from '@/components/ui/input';
import { Field, FieldLabel } from '@/components/ui/field';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { useState } from 'react';
import { LoaderCircle, Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { KnowledgeSearchResponse } from '../../../types/knowledge';
import { knowledgeApi } from '../../../api/knowledge';
import { Feedback, useResourceTask } from '../resources/ResourceUI';

export function KnowledgeSearch({ baseId }: { baseId: string }) {
  const { t } = useTranslation('knowledge');
  const [query, setQuery] = useState('');
  const [response, setResponse] = useState<KnowledgeSearchResponse | null>(null);
  const task = useResourceTask();
  return (
    <div className="resource-test">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void task.run('search', async () => {
            setResponse(null);
            setResponse(
              await knowledgeApi.searchKnowledge({ query, knowledge_base_ids: [baseId], debug: true }),
            );
          });
        }}
      >
        <Field>
          <FieldLabel>{t('query')}</FieldLabel>
          <Input required value={query} onChange={(event) => setQuery(event.target.value)} />
        </Field>
        <Button type="submit" disabled={!!task.busy || !query.trim()} variant="outline">
          {task.busy ? (
            <LoaderCircle data-icon="inline-start" className="animate-spin" />
          ) : (
            <Search data-icon="inline-start" />
          )}
          {t('search')}
        </Button>
      </form>
      <Feedback {...task} />
      {response ? (
        <div className="knowledge-search-results">
          {response.metadata?.rerank_fallback ? (
            <p className="resource-warning">{t('rerankFallback')}</p>
          ) : null}
          {response.results.map((item, index) => (
            <article className="knowledge-result" key={item.chunk_id}>
              <div className="resource-toolbar">
                <strong>
                  {index + 1}. {item.title || item.source_id}
                </strong>
              </div>
              {item.heading_path ? <small>{item.heading_path}</small> : null}
              <p>{item.content}</p>
              {item.truncated ? <small>{t('truncated')}</small> : null}
              <Collapsible className="resource-advanced">
                <CollapsibleTrigger
                  render={<Button type="button" variant="ghost" className="justify-start" />}
                >
                  {t('scores')}
                </CollapsibleTrigger>
                <CollapsibleContent keepMounted>
                  <dl className="resource-metrics">
                    {(['vector_score', 'keyword_score', 'rrf_score', 'rerank_score'] as const).map((key) => (
                      <div key={key}>
                        <dt>{t(key)}</dt>
                        <dd>{item[key]?.toFixed(5) ?? t('notAvailable')}</dd>
                      </div>
                    ))}
                  </dl>
                </CollapsibleContent>
              </Collapsible>
            </article>
          ))}
          {!response.results.length ? <p className="resource-empty">{t('noResults')}</p> : null}
          <Collapsible className="resource-advanced">
            <CollapsibleTrigger render={<Button type="button" variant="ghost" className="justify-start" />}>
              {t('contextPreview')}
            </CollapsibleTrigger>
            <CollapsibleContent keepMounted>
              <pre>{response.context_preview || t('noResults')}</pre>
            </CollapsibleContent>
          </Collapsible>
          {response.debug ? (
            <Collapsible className="resource-advanced">
              <CollapsibleTrigger render={<Button type="button" variant="ghost" className="justify-start" />}>
                {t('diagnostics')}
              </CollapsibleTrigger>
              <CollapsibleContent keepMounted>
                <pre>{JSON.stringify(response.debug, null, 2)}</pre>
              </CollapsibleContent>
            </Collapsible>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
