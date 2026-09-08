import { useState } from 'react';
import { LoaderCircle, Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { KnowledgeSearchResponse } from '../../../types/knowledge';
import { knowledgeApi } from '../../../api/knowledge';
import { Feedback, Field, useResourceTask } from '../resources/ResourceUI';

export function KnowledgeSearch({ baseId }: { baseId: string }) {
  const { t } = useTranslation('knowledge');
  const [query, setQuery] = useState('');
  const [response, setResponse] = useState<KnowledgeSearchResponse | null>(null);
  const task = useResourceTask();
  return <div className="resource-test">
    <form onSubmit={(event) => { event.preventDefault(); void task.run('search', async () => { setResponse(null); setResponse(await knowledgeApi.searchKnowledge({ query, knowledge_base_ids: [baseId], debug: true })); }); }}>
      <Field label={t('query')}><input required value={query} onChange={(event) => setQuery(event.target.value)} /></Field>
      <button type="submit" className="secondary-button" disabled={!!task.busy || !query.trim()}>{task.busy ? <LoaderCircle size={16} className="spin" /> : <Search size={16} />}{t('search')}</button>
    </form>
    <Feedback {...task} />
    {response ? <div className="knowledge-search-results">
      {response.metadata?.rerank_fallback ? <p className="resource-warning">{t('rerankFallback')}</p> : null}
      {response.results.map((item, index) => <article className="knowledge-result" key={item.chunk_id}>
        <div className="resource-toolbar"><strong>{index + 1}. {item.title || item.source_id}</strong></div>
        {item.heading_path ? <small>{item.heading_path}</small> : null}<p>{item.content}</p>
        {item.truncated ? <small>{t('truncated')}</small> : null}
        <details className="resource-advanced"><summary>{t('scores')}</summary><dl className="resource-metrics">
          {(['vector_score', 'keyword_score', 'rrf_score', 'rerank_score'] as const).map((key) => <div key={key}><dt>{t(key)}</dt><dd>{item[key]?.toFixed(5) ?? t('notAvailable')}</dd></div>)}
        </dl></details>
      </article>)}
      {!response.results.length ? <p className="resource-empty">{t('noResults')}</p> : null}
      <details className="resource-advanced"><summary>{t('contextPreview')}</summary><pre>{response.context_preview || t('noResults')}</pre></details>
      {response.debug ? <details className="resource-advanced"><summary>{t('diagnostics')}</summary><pre>{JSON.stringify(response.debug, null, 2)}</pre></details> : null}
    </div> : null}
  </div>;
}
