import { useEffect, useState } from 'react';
import { RefreshCw, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { knowledgeApi } from '../../../api/knowledge';
import type { KnowledgeSource, KnowledgeSourceChunk, KnowledgeSourcePreview } from '../../../types/knowledge';
import { AppModal } from '../../ui/AppModal';
import { errorText, ResourceIcon, ResourceLoading } from '../resources/ResourceUI';

export function KnowledgeSourceDetail({ source, revision, busy, operationError, notice, onClose, onReindex, onDelete }: {
  source: KnowledgeSource; revision: number; busy: boolean; onClose: () => void; onReindex: () => void; onDelete: () => void;
  operationError: string; notice: string;
}) {
  const { t, i18n } = useTranslation('knowledge');
  const [preview, setPreview] = useState<KnowledgeSourcePreview | null>(null);
  const [chunks, setChunks] = useState<KnowledgeSourceChunk[] | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let live = true; setPreview(null); setChunks(null); setError('');
    void Promise.allSettled([knowledgeApi.getKnowledgeSourcePreview(source.id), knowledgeApi.listKnowledgeSourceChunks(source.id)]).then(([text, parts]) => {
      if (!live) return;
      if (text.status === 'fulfilled') setPreview(text.value);
      if (parts.status === 'fulfilled') setChunks(parts.value.chunks);
      setError([text, parts].filter((result) => result.status === 'rejected').map((result) => errorText((result as PromiseRejectedResult).reason)).join('\n'));
    });
    return () => { live = false; };
  }, [source.id, revision, reload]);
  return <AppModal open title={source.title} closeLabel={t('close')} width="large" onClose={onClose} className="resource-modal">
    <div className="resource-toolbar"><span className={`resource-badge ${source.status === 'indexed' ? 'active' : 'warning'}`}>{t('statuses.' + source.status)}</span>
      <div className="resource-actions"><ResourceIcon label={t('reindex')} disabled={busy} onClick={onReindex}><RefreshCw size={16} /></ResourceIcon>
        <ResourceIcon label={t('common:delete')} danger disabled={busy} onClick={onDelete}><Trash2 size={16} /></ResourceIcon></div></div>
    <dl className="resource-metrics"><div><dt>{t('sourceType')}</dt><dd>{t('sourceTypes.' + source.source_type)}</dd></div>
      <div><dt>{t('chunks')}</dt><dd>{source.chunks}</dd></div><div><dt>{t('size')}</dt><dd>{source.size_bytes.toLocaleString(i18n.language)} B</dd></div>
      <div><dt>{t('indexedAt')}</dt><dd>{source.indexed_at ? new Date(source.indexed_at).toLocaleString(i18n.language) : t('notIndexed')}</dd></div></dl>
    {source.error ? <p className="error-text">{source.error}</p> : null}
    {operationError ? <p className="error-text" role="alert">{operationError}</p> : notice ? <p className="success-text" role="status">{notice}</p> : null}
    {error ? <ResourceLoading error={error} retry={() => setReload((value) => value + 1)} /> : !preview || !chunks ? <ResourceLoading /> : null}
    <h3>{t('sourcePreview')}</h3>{preview ? <><pre className="knowledge-source-preview">{preview.content}</pre>{preview.truncated ? <p className="resource-warning">{t('truncated')}</p> : null}</> : null}
    <h3>{t('chunks')}</h3>
    {chunks?.map((chunk) => <details className="knowledge-chunk" key={chunk.chunk_id}>
      <summary>{t('chunkNumber', { index: chunk.chunk_index + 1 })}<span>{chunk.char_start}-{chunk.char_end}</span></summary>
      {chunk.heading_path ? <small>{chunk.heading_path}</small> : null}<pre>{chunk.content}</pre>
    </details>)}
    {chunks?.length === 0 ? <p className="resource-empty">{t('noChunks')}</p> : null}
  </AppModal>;
}
