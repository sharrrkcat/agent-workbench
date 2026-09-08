import { useCallback, useEffect, useState } from 'react';
import { Clipboard, Eye, LoaderCircle, RefreshCw, Trash2, Upload } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { knowledgeApi } from '../../../api/knowledge';
import type { KnowledgeBase, KnowledgeSource } from '../../../types/knowledge';
import { errorText, Feedback, ResourceIcon, ResourceLoading, useResourceTask } from '../resources/ResourceUI';
import { AddKnowledgeSource } from './AddKnowledgeSource';
import { KnowledgeSourceDetail } from './KnowledgeSourceDetail';

export function KnowledgeSources({ baseId, revision, onBase, onState }: {
  baseId: string; revision: number; onBase: (base: KnowledgeBase) => void;
  onState: (state: { dirty: boolean; busy: boolean }) => void;
}) {
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
  useEffect(() => { onState({ dirty: uploadState.dirty, busy: locked }); }, [uploadState.dirty, locked, onState]);
  useEffect(() => {
    let live = true; setLoading(true); setLoadError('');
    void knowledgeApi.listKnowledgeSources(baseId).then((items) => { if (live) { setSources(items); setLoading(false); } })
      .catch((reason) => { if (live) { setLoadError(errorText(reason)); setLoading(false); } });
    return () => { live = false; };
  }, [baseId, revision, reload]);
  const refresh = useCallback(async () => {
    const [items, base] = await Promise.all([knowledgeApi.listKnowledgeSources(baseId), knowledgeApi.getKnowledgeBase(baseId)]);
    setSources(items); onBase(base); setPreviewRevision((value) => value + 1);
  }, [baseId, onBase]);
  async function reindex(id?: string) {
    const result = await task.run(id || 'all', async () => {
      const results = id ? [await knowledgeApi.reindexKnowledgeSource(id)] : (await knowledgeApi.reindexKnowledgeBase(baseId)).sources;
      await refresh();
      return results;
    });
    if (result) { const failed = result.filter((item) => item.status !== 'indexed').length; task.setNotice(t('reindexResult', { count: result.length - failed, failed })); }
  }
  function remove(source: KnowledgeSource) {
    if (!window.confirm(t('deleteSourceConfirm', { name: source.title }))) return;
    void task.run('delete', async () => {
      await knowledgeApi.deleteKnowledgeSource(source.id);
      setSources((current) => current.filter((item) => item.id !== source.id));
      if (sourceId === source.id) setSourceId('');
      await refresh();
    }, t('sourceDeleted'));
  }
  const selected = sources.find((source) => source.id === sourceId);
  return <div className="knowledge-sources">
    <div className="resource-toolbar"><h3>{t('sources')} <span className="resource-count">{sources.length}</span></h3>
      <div className="resource-actions">
        <ResourceIcon label={t('settings:resources.refresh')} disabled={locked} onClick={() => setReload((value) => value + 1)}><RefreshCw size={16} /></ResourceIcon>
        <button type="button" className="secondary-button" disabled={locked || !!modal} onClick={() => setModal('paste')}><Clipboard size={15} />{t('pasteText')}</button>
        <button type="button" className="secondary-button" disabled={locked || !!modal} onClick={() => setModal('upload')}><Upload size={15} />{t('uploadFiles')}</button>
      </div></div>
    <div className="resource-toolbar"><span />
      <button type="button" className="secondary-button" disabled={locked || !sources.length} onClick={() => void reindex()}>{task.busy === 'all' ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}{t('reindexAll')}</button></div>
    <Feedback {...task} />
    {loading || loadError ? <ResourceLoading error={loadError} retry={() => setReload((value) => value + 1)} /> : sources.length ? <div className="knowledge-table-scroll"><table className="knowledge-sources-table">
      <thead><tr><th>{t('sourceTitle')}</th><th>{t('sourceType')}</th><th>{t('chunks')}</th><th>{t('index')}</th><th><span className="sr-only">{t('actions')}</span></th></tr></thead>
      <tbody>{sources.map((source) => <tr key={source.id}>
        <td><button type="button" className="resource-source-link" onClick={() => setSourceId(source.id)}>{source.title}</button>{source.error ? <small className="error-text">{source.error}</small> : null}</td>
        <td>{t('sourceTypes.' + source.source_type)}</td><td data-unit={t('chunks')}>{source.chunks}</td>
        <td><span className={`resource-badge ${source.status === 'indexed' ? 'active' : 'warning'}`}>{t('statuses.' + source.status)}</span>
          <small>{source.indexed_at ? new Date(source.indexed_at).toLocaleString(i18n.language) : t('notIndexed')}</small></td>
        <td><div className="resource-actions"><ResourceIcon label={t('sourceDetail')} onClick={() => setSourceId(source.id)}><Eye size={15} /></ResourceIcon>
          <ResourceIcon label={t('reindex')} disabled={locked} busy={task.busy === source.id} onClick={() => void reindex(source.id)}><RefreshCw size={15} /></ResourceIcon>
          <ResourceIcon label={t('common:delete')} danger disabled={locked} onClick={() => remove(source)}><Trash2 size={15} /></ResourceIcon></div></td>
      </tr>)}</tbody>
    </table></div> : <p className="resource-empty">{t('noSources')}</p>}
    {selected && !modal ? <KnowledgeSourceDetail key={selected.id} source={selected} revision={previewRevision} busy={locked} operationError={task.error} notice={task.notice} onClose={() => setSourceId('')}
      onReindex={() => void reindex(selected.id)} onDelete={() => remove(selected)} /> : null}
    {modal ? <AddKnowledgeSource baseId={baseId} mode={modal} onState={setUploadState} onClose={() => { setModal(null); setUploadState({ dirty: false, busy: false }); }}
      onAdded={async (id) => { setSourceId(id); try { await refresh(); } catch (reason) { task.setError(errorText(reason)); } }} /> : null}
  </div>;
}
