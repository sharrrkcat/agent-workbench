import { Badge } from '@/components/ui/badge';
import { ResourceEmpty } from '../resources/ResourceUI';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { useCallback, useEffect, useState } from 'react';
import { Clipboard, Eye, LoaderCircle, RefreshCw, Trash2, Upload } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { knowledgeApi } from '../../../api/knowledge';
import type { KnowledgeBase, KnowledgeSource } from '../../../types/knowledge';
import { errorText, Feedback, ResourceLoading, useResourceTask } from '../resources/ResourceUI';
import { AddKnowledgeSource } from './AddKnowledgeSource';
import { KnowledgeSourceDetail } from './KnowledgeSourceDetail';

export function KnowledgeSources({
  baseId,
  revision,
  onBase,
  onState,
}: {
  baseId: string;
  revision: number;
  onBase: (base: KnowledgeBase) => void;
  onState: (state: { dirty: boolean; busy: boolean }) => void;
}) {
  const { confirm, confirmation } = useConfirmDialog();
  const { t, i18n } = useTranslation('knowledge');
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [reload, setReload] = useState(0);
  const [sourceId, setSourceId] = useState('');
  const [previewRevision, setPreviewRevision] = useState(0);
  const [modal, setModal] = useState<'paste' | 'upload' | null>(null);
  const [uploadState, setUploadState] = useState({ dirty: false, busy: false });
  const task = useResourceTask();
  const locked = !!task.busy || uploadState.busy;
  useEffect(() => {
    onState({ dirty: uploadState.dirty, busy: locked });
  }, [uploadState.dirty, locked, onState]);
  useEffect(() => {
    let live = true;
    setLoading(true);
    setLoadError('');
    void knowledgeApi
      .listKnowledgeSources(baseId)
      .then((items) => {
        if (live) {
          setSources(items);
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
  }, [baseId, revision, reload]);
  const refresh = useCallback(async () => {
    const [items, base] = await Promise.all([
      knowledgeApi.listKnowledgeSources(baseId),
      knowledgeApi.getKnowledgeBase(baseId),
    ]);
    setSources(items);
    onBase(base);
    setPreviewRevision((value) => value + 1);
  }, [baseId, onBase]);
  async function reindex(id?: string) {
    const result = await task.run(id || 'all', async () => {
      const results = id
        ? [await knowledgeApi.reindexKnowledgeSource(id)]
        : (await knowledgeApi.reindexKnowledgeBase(baseId)).sources;
      await refresh();
      return results;
    });
    if (result) {
      const failed = result.filter((item) => item.status !== 'indexed').length;
      task.setNotice(t('reindexResult', { count: result.length - failed, failed }));
    }
  }
  async function remove(source: KnowledgeSource) {
    if (!(await confirm(t('deleteSourceConfirm', { name: source.title }), { destructive: true }))) return;
    void task.run(
      'delete',
      async () => {
        await knowledgeApi.deleteKnowledgeSource(source.id);
        setSources((current) => current.filter((item) => item.id !== source.id));
        if (sourceId === source.id) setSourceId('');
        await refresh();
      },
      t('sourceDeleted'),
    );
  }
  const selected = sources.find((source) => source.id === sourceId);
  return (
    <div className="knowledge-sources">
      <div className="resource-toolbar">
        <h3>
          {t('sources')} <span className="resource-count">{sources.length}</span>
        </h3>
        <div className="resource-actions">
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={t('settings:resources.refresh')}
                  disabled={locked}
                  onClick={() => setReload((value) => value + 1)}
                />
              }
            >
              <RefreshCw data-icon="inline-start" />
            </TooltipTrigger>
            <TooltipContent>{t('settings:resources.refresh')}</TooltipContent>
          </Tooltip>
          <Button
            type="button"
            disabled={locked || !!modal}
            onClick={() => setModal('paste')}
            variant="outline"
          >
            <Clipboard data-icon="inline-start" />
            {t('pasteText')}
          </Button>
          <Button
            type="button"
            disabled={locked || !!modal}
            onClick={() => setModal('upload')}
            variant="outline"
          >
            <Upload data-icon="inline-start" />
            {t('uploadFiles')}
          </Button>
        </div>
      </div>
      <div className="resource-toolbar">
        <span />
        <Button
          type="button"
          disabled={locked || !sources.length}
          onClick={() => void reindex()}
          variant="outline"
        >
          {task.busy === 'all' ? (
            <LoaderCircle data-icon="inline-start" className="animate-spin" />
          ) : (
            <RefreshCw data-icon="inline-start" />
          )}
          {t('reindexAll')}
        </Button>
      </div>
      <Feedback {...task} />
      {loading || loadError ? (
        <ResourceLoading error={loadError} retry={() => setReload((value) => value + 1)} />
      ) : sources.length ? (
        <div className="knowledge-table-scroll">
          <Table className="knowledge-sources-table">
            <TableHeader>
              <TableRow>
                <TableHead>{t('sourceTitle')}</TableHead>
                <TableHead>{t('sourceType')}</TableHead>
                <TableHead>{t('chunks')}</TableHead>
                <TableHead>{t('index')}</TableHead>
                <TableHead>
                  <span className="sr-only">{t('actions')}</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sources.map((source) => (
                <TableRow key={source.id}>
                  <TableCell>
                    <Button
                      type="button"
                      onClick={() => setSourceId(source.id)}
                      variant="ghost"
                      className="resource-source-link h-auto max-w-72 justify-start whitespace-normal text-left"
                    >
                      {source.title}
                    </Button>
                    {source.error ? <small className="error-text">{source.error}</small> : null}
                  </TableCell>
                  <TableCell>{t('sourceTypes.' + source.source_type)}</TableCell>
                  <TableCell data-unit={t('chunks')}>{source.chunks}</TableCell>
                  <TableCell>
                    <Badge variant="secondary">{t('statuses.' + source.status)}</Badge>
                    <small>
                      {source.indexed_at
                        ? new Date(source.indexed_at).toLocaleString(i18n.language)
                        : t('notIndexed')}
                    </small>
                  </TableCell>
                  <TableCell>
                    <div className="resource-actions">
                      <Tooltip>
                        <TooltipTrigger
                          render={
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              aria-label={t('sourceDetail')}
                              onClick={() => setSourceId(source.id)}
                            />
                          }
                        >
                          <Eye data-icon="inline-start" />
                        </TooltipTrigger>
                        <TooltipContent>{t('sourceDetail')}</TooltipContent>
                      </Tooltip>
                      <Tooltip>
                        <TooltipTrigger
                          render={
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              aria-label={t('reindex')}
                              disabled={locked || task.busy === source.id}
                              onClick={() => void reindex(source.id)}
                            />
                          }
                        >
                          {task.busy === source.id ? (
                            <LoaderCircle className="animate-spin" />
                          ) : (
                            <>
                              <RefreshCw data-icon="inline-start" />
                            </>
                          )}
                        </TooltipTrigger>
                        <TooltipContent>{t('reindex')}</TooltipContent>
                      </Tooltip>
                      <Tooltip>
                        <TooltipTrigger
                          render={
                            <Button
                              type="button"
                              variant="destructive"
                              size="icon"
                              aria-label={t('common:delete')}
                              disabled={locked}
                              onClick={() => remove(source)}
                            />
                          }
                        >
                          <Trash2 data-icon="inline-start" />
                        </TooltipTrigger>
                        <TooltipContent>{t('common:delete')}</TooltipContent>
                      </Tooltip>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <ResourceEmpty>{t('noSources')}</ResourceEmpty>
      )}
      {selected && !modal ? (
        <KnowledgeSourceDetail
          key={selected.id}
          source={selected}
          revision={previewRevision}
          busy={locked}
          operationError={task.error}
          notice={task.notice}
          onClose={() => setSourceId('')}
          onReindex={() => void reindex(selected.id)}
          onDelete={() => remove(selected)}
        />
      ) : null}
      {modal ? (
        <AddKnowledgeSource
          baseId={baseId}
          mode={modal}
          onState={setUploadState}
          onClose={() => {
            setModal(null);
            setUploadState({ dirty: false, busy: false });
          }}
          onAdded={async (id) => {
            setSourceId(id);
            try {
              await refresh();
            } catch (reason) {
              task.setError(errorText(reason));
            }
          }}
        />
      ) : null}
      {confirmation}
    </div>
  );
}
