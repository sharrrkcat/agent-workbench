import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { useEffect, useState } from 'react';
import { RefreshCw, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { knowledgeApi } from '../../../api/knowledge';
import type { KnowledgeSource, KnowledgeSourceChunk, KnowledgeSourcePreview } from '../../../types/knowledge';

import { errorText, Feedback, ResourceEmpty, ResourceLoading } from '../resources/ResourceUI';

export function KnowledgeSourceDetail({
  source,
  revision,
  busy,
  operationError,
  notice,
  onClose,
  onReindex,
  onDelete,
}: {
  source: KnowledgeSource;
  revision: number;
  busy: boolean;
  onClose: () => void;
  onReindex: () => void;
  onDelete: () => void;
  operationError: string;
  notice: string;
}) {
  const { t, i18n } = useTranslation('knowledge');
  const [preview, setPreview] = useState<KnowledgeSourcePreview | null>(null);
  const [chunks, setChunks] = useState<KnowledgeSourceChunk[] | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let live = true;
    setPreview(null);
    setChunks(null);
    setError('');
    void Promise.allSettled([
      knowledgeApi.getKnowledgeSourcePreview(source.id),
      knowledgeApi.listKnowledgeSourceChunks(source.id),
    ]).then(([text, parts]) => {
      if (!live) return;
      if (text.status === 'fulfilled') setPreview(text.value);
      if (parts.status === 'fulfilled') setChunks(parts.value.chunks);
      setError(
        [text, parts]
          .filter((result) => result.status === 'rejected')
          .map((result) => errorText((result as PromiseRejectedResult).reason))
          .join('\n'),
      );
    });
    return () => {
      live = false;
    };
  }, [source.id, revision, reload]);
  return (
    <Dialog
      open={true}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="resource-modal sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{source.title}</DialogTitle>
        </DialogHeader>
        <div className="settings-dialog-body knowledge-source-content">
          <Badge variant="secondary" className="self-start">
            {t('statuses.' + source.status)}
          </Badge>
          <dl className="resource-metrics">
            <div>
              <dt>{t('sourceType')}</dt>
              <dd>{t('sourceTypes.' + source.source_type)}</dd>
            </div>
            <div>
              <dt>{t('chunks')}</dt>
              <dd>{source.chunks}</dd>
            </div>
            <div>
              <dt>{t('size')}</dt>
              <dd>{source.size_bytes.toLocaleString(i18n.language)} B</dd>
            </div>
            <div>
              <dt>{t('indexedAt')}</dt>
              <dd>
                {source.indexed_at
                  ? new Date(source.indexed_at).toLocaleString(i18n.language)
                  : t('notIndexed')}
              </dd>
            </div>
          </dl>
          {source.error ? <p className="error-text">{source.error}</p> : null}
          <Feedback error={operationError} notice={notice} />
          {error ? (
            <ResourceLoading error={error} retry={() => setReload((value) => value + 1)} />
          ) : !preview || !chunks ? (
            <ResourceLoading />
          ) : null}
          <h3 className="font-semibold">{t('sourcePreview')}</h3>
          {preview ? (
            <>
              <pre className="knowledge-source-preview">{preview.content}</pre>
              {preview.truncated ? <p className="resource-warning">{t('truncated')}</p> : null}
            </>
          ) : null}
          <h3 className="font-semibold">{t('chunks')}</h3>
          {chunks?.map((chunk) => (
            <Collapsible className="knowledge-chunk" key={chunk.chunk_id}>
              <CollapsibleTrigger render={<Button type="button" variant="ghost" className="justify-start" />}>
                {t('chunkNumber', { index: chunk.chunk_index + 1 })}
                <span>
                  {chunk.char_start}-{chunk.char_end}
                </span>
              </CollapsibleTrigger>
              <CollapsibleContent keepMounted>
                {chunk.heading_path ? <small>{chunk.heading_path}</small> : null}
                <pre>{chunk.content}</pre>
              </CollapsibleContent>
            </Collapsible>
          ))}
          {chunks?.length === 0 ? <ResourceEmpty>{t('noChunks')}</ResourceEmpty> : null}
        </div>
        <DialogFooter className="shrink-0">
          <Button type="button" variant="outline" disabled={busy} onClick={onReindex}>
            <RefreshCw data-icon="inline-start" />
            {t('reindex')}
          </Button>
          <Button type="button" variant="destructive" disabled={busy} onClick={onDelete}>
            <Trash2 data-icon="inline-start" />
            {t('common:delete')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
