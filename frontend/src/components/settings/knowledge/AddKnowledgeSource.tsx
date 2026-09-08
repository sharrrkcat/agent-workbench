import { useEffect, useRef, useState } from 'react';
import { Clipboard, LoaderCircle, Plus, RefreshCw, Upload, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { chatApi } from '../../../api/chat';
import { knowledgeApi } from '../../../api/knowledge';
import type { KnowledgeSourceIndexResult } from '../../../types/knowledge';
import { AppModal } from '../../ui/AppModal';
import { errorText, Feedback, Field, ResourceIcon, useResourceTask } from '../resources/ResourceUI';

type UploadItem = { id: string; file: File; attachmentId?: string; status: 'queued' | 'uploading' | 'indexing' | 'indexed' | 'failed'; error?: string; chunks?: number };
export const knowledgeTextExtensions = '.txt,.md,.py,.js,.ts,.tsx,.jsx,.json,.yaml,.yml,.toml,.xml,.html,.css,.env,.log,.csv,.sql,.sh,.ps1,.bat,.ini,.cfg';

export function AddKnowledgeSource({ baseId, mode, onClose, onAdded, onState }: {
  baseId: string; mode: 'paste' | 'upload'; onClose: () => void; onAdded: (sourceId: string) => Promise<void>;
  onState: (state: { dirty: boolean; busy: boolean }) => void;
}) {
  const { t } = useTranslation('knowledge');
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [items, setItems] = useState<UploadItem[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const temporary = useRef(new Set<string>());
  const task = useResourceTask();
  const dirty = !!title || !!text || items.some((item) => item.status !== 'indexed');
  useEffect(() => { onState({ dirty, busy: !!task.busy }); }, [dirty, task.busy, onState]);
  useEffect(() => () => {
    for (const id of temporary.current) void chatApi.deleteAttachment(id).catch(() => undefined);
  }, []);
  function close() {
    if (task.busy || (dirty && !window.confirm(t('settings:resources.discardConfirm')))) return;
    onClose();
  }
  function update(id: string, patch: Partial<UploadItem>) { setItems((current) => current.map((item) => item.id === id ? { ...item, ...patch } : item)); }
  async function indexed(result: KnowledgeSourceIndexResult) {
    if (result.status !== 'indexed') throw new Error(result.error || t('indexFailed'));
    await onAdded(result.source_id);
  }
  async function upload() {
    await task.run('upload', async () => {
      for (const item of items.filter((value) => value.status !== 'indexed')) {
        let attachmentId = item.attachmentId;
        try {
          if (!attachmentId) {
            update(item.id, { status: 'uploading', error: '' });
            const attachment = await chatApi.uploadAttachment(item.file);
            if (!attachment.uri) throw new Error(t('uploadFailed'));
            attachmentId = new URL(attachment.uri).pathname.slice(1);
            temporary.current.add(attachmentId); update(item.id, { attachmentId });
          }
          update(item.id, { status: 'indexing', error: '' });
          const result = await knowledgeApi.createAttachmentKnowledgeSource(baseId, attachmentId, item.file.name);
          if (result.status !== 'indexed') throw new Error(result.error || t('indexFailed'));
          temporary.current.delete(attachmentId);
          update(item.id, { status: 'indexed', chunks: result.chunks, error: '' });
          await onAdded(result.source_id);
        } catch (reason) { update(item.id, { status: 'failed', error: errorText(reason) }); }
      }
    });
  }
  return <AppModal open title={t(mode === 'paste' ? 'pasteText' : 'uploadFiles')} closeLabel={t('close')} width="large" onClose={close} className="resource-modal">
    <Feedback {...task} />
    {mode === 'paste' ? <form onSubmit={(event) => { event.preventDefault(); void task.run('paste', async () => {
      const result = await knowledgeApi.createPastedKnowledgeSource(baseId, title, text);
      if (result.status !== 'indexed') throw new Error(result.error || t('indexFailed'));
      setTitle(''); setText(''); await indexed(result); onClose();
    }); }}><fieldset className="resource-fieldset" disabled={!!task.busy}>
      <Field label={t('sourceTitle')}><input required value={title} onChange={(event) => setTitle(event.target.value)} /></Field>
      <Field label={t('sourceText')}><textarea required rows={10} value={text} onChange={(event) => setText(event.target.value)} /></Field>
      <div className="resource-form-footer"><button type="submit" className="primary-button" disabled={!title.trim() || !text.trim()}>{task.busy ? <LoaderCircle size={16} className="spin" /> : <Clipboard size={16} />}{t('addAndIndex')}</button></div>
    </fieldset></form> : <>
      <input type="file" multiple accept={knowledgeTextExtensions} hidden ref={input} onChange={(event) => {
        const files = Array.from(event.target.files || []); event.target.value = '';
        setItems((current) => [...current, ...files.map((file) => ({ id: crypto.randomUUID(), file, status: 'queued' as const }))]);
      }} />
      <button type="button" className="secondary-button" disabled={!!task.busy} onClick={() => input.current?.click()}><Plus size={16} />{t('chooseFiles')}</button>
      <div className="knowledge-upload-list">{items.map((item) => <div className="resource-row" key={item.id}>
        <div className="resource-identity"><strong>{item.file.name}</strong><small>{t('uploadStates.' + item.status)}{item.chunks !== undefined ? ` · ${t('chunkCount', { count: item.chunks })}` : ''}</small>
          {item.error ? <span className="error-text">{item.error}</span> : null}</div>
        <ResourceIcon label={t('removeFile')} disabled={!!task.busy} onClick={() => {
          if (item.attachmentId && temporary.current.has(item.attachmentId)) { temporary.current.delete(item.attachmentId); void chatApi.deleteAttachment(item.attachmentId).catch(() => undefined); }
          setItems((current) => current.filter((value) => value.id !== item.id));
        }}><X size={16} /></ResourceIcon>
      </div>)}</div>
      <div className="resource-form-footer"><button type="button" className="primary-button" disabled={!!task.busy || !items.some((item) => item.status !== 'indexed')} onClick={() => void upload()}>
        {task.busy ? <LoaderCircle size={16} className="spin" /> : items.some((item) => item.status === 'failed') ? <RefreshCw size={16} /> : <Upload size={16} />}{t(items.some((item) => item.status === 'failed') ? 'retryFailed' : 'addAndIndex')}</button></div>
    </>}
  </AppModal>;
}
