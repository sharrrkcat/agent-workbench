import { useState } from 'react';
import { LoaderCircle, Play } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { worldbookApi } from '../../../api/worldbook';
import type { WorldbookMatchResponse } from '../../../types/worldbook';
import { Feedback, Field, useResourceTask } from '../resources/ResourceUI';

export function WorldbookMatch({ bookId }: { bookId: string }) {
  const { t } = useTranslation('worldbook');
  const [text, setText] = useState('');
  const [result, setResult] = useState<WorldbookMatchResponse | null>(null);
  const task = useResourceTask();
  return <div className="resource-test">
    <form onSubmit={(event) => { event.preventDefault(); void task.run('match', async () => { setResult(null); setResult(await worldbookApi.matchWorldbooks({ text, worldbook_ids: [bookId] })); }); }}>
      <Field label={t('matchText')}><textarea rows={5} value={text} onChange={(event) => setText(event.target.value)} /></Field>
      <button type="submit" className="secondary-button" disabled={!!task.busy}>{task.busy ? <LoaderCircle size={16} className="spin" /> : <Play size={16} />}{t('matchTest')}</button>
    </form>
    <Feedback {...task} />
    {result ? <div className="worldbook-match-results">
      <p className="resource-summary">{t('matchCounts', { matched: result.matched_count, included: result.included_count })}</p>
      {result.warnings.map((warning, index) => <p className="resource-warning" key={index}>{warning.code === 'WORLDBOOK_CONTEXT_TRUNCATED' ? t('truncated') : warning.message}</p>)}
      {result.results.map((item) => <article className="worldbook-match-entry-card" key={item.entry_id}>
        <div className="resource-toolbar"><strong>{item.entry_name}</strong><span className="resource-badge">{t(item.activation_mode)}</span></div>
        <small>{item.matched_keywords.join(', ')}{item.matched_by_recursion ? ` · ${t('recursionMatch', { depth: item.recursion_depth })}` : ''}</small>
        <p>{item.content_preview}</p>
      </article>)}
      {!result.results.length ? <p className="resource-empty">{t('noMatches')}</p> : null}
    </div> : null}
  </div>;
}
