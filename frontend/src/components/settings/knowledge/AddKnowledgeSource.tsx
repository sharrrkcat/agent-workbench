import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { Input } from '@/components/ui/input';
import { Field, FieldLabel, FieldSet } from '@/components/ui/field';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { useEffect, useRef, useState } from 'react';
import { Clipboard, LoaderCircle, Plus, RefreshCw, Upload, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { chatApi } from '../../../api/chat';
import { knowledgeApi } from '../../../api/knowledge';
import type { KnowledgeSourceIndexResult } from '../../../types/knowledge';

import { errorText, Feedback, useResourceTask } from '../resources/ResourceUI';

type UploadItem = {
  id: string;
  file: File;
  attachmentId?: string;
  status: 'queued' | 'uploading' | 'indexing' | 'indexed' | 'failed';
  error?: string;
  chunks?: number;
};
export const knowledgeTextExtensions =
  '.txt,.md,.py,.js,.ts,.tsx,.jsx,.json,.yaml,.yml,.toml,.xml,.html,.css,.env,.log,.csv,.sql,.sh,.ps1,.bat,.ini,.cfg';

export function AddKnowledgeSource({
  baseId,
  mode,
  onClose,
  onAdded,
  onState,
}: {
  baseId: string;
  mode: 'paste' | 'upload';
  onClose: () => void;
  onAdded: (sourceId: string) => Promise<void>;
  onState: (state: { dirty: boolean; busy: boolean }) => void;
}) {
  const { confirm, confirmation } = useConfirmDialog();
  const { t } = useTranslation('knowledge');
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [items, setItems] = useState<UploadItem[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const temporary = useRef(new Set<string>());
  const task = useResourceTask();
  const dirty = !!title || !!text || items.some((item) => item.status !== 'indexed');
  useEffect(() => {
    onState({ dirty, busy: !!task.busy });
  }, [dirty, task.busy, onState]);
  useEffect(
    () => () => {
      for (const id of temporary.current) void chatApi.deleteAttachment(id).catch(() => undefined);
    },
    [],
  );
  async function close() {
    if (task.busy || (dirty && !(await confirm(t('settings:resources.discardConfirm'))))) return;
    onClose();
  }
  function update(id: string, patch: Partial<UploadItem>) {
    setItems((current) => current.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  }
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
            temporary.current.add(attachmentId);
            update(item.id, { attachmentId });
          }
          update(item.id, { status: 'indexing', error: '' });
          const result = await knowledgeApi.createAttachmentKnowledgeSource(
            baseId,
            attachmentId,
            item.file.name,
          );
          if (result.status !== 'indexed') throw new Error(result.error || t('indexFailed'));
          temporary.current.delete(attachmentId);
          update(item.id, { status: 'indexed', chunks: result.chunks, error: '' });
          await onAdded(result.source_id);
        } catch (reason) {
          update(item.id, { status: 'failed', error: errorText(reason) });
        }
      }
    });
  }
  return (
    <Dialog
      open={true}
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <DialogContent className={'sm:max-w-3xl' + ' ' + 'resource-modal'}>
        <DialogHeader>
          <DialogTitle>{t(mode === 'paste' ? 'pasteText' : 'uploadFiles')}</DialogTitle>
        </DialogHeader>
        <div className="min-h-0 overflow-y-auto overscroll-contain">
          <Feedback {...task} />
          {mode === 'paste' ? (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void task.run('paste', async () => {
                  const result = await knowledgeApi.createPastedKnowledgeSource(baseId, title, text);
                  if (result.status !== 'indexed') throw new Error(result.error || t('indexFailed'));
                  setTitle('');
                  setText('');
                  await indexed(result);
                  onClose();
                });
              }}
            >
              <FieldSet className="resource-fieldset" disabled={!!task.busy}>
                <Field>
                  <FieldLabel>{t('sourceTitle')}</FieldLabel>
                  <Input required value={title} onChange={(event) => setTitle(event.target.value)} />
                </Field>
                <Field>
                  <FieldLabel>{t('sourceText')}</FieldLabel>
                  <Textarea
                    required
                    rows={10}
                    value={text}
                    onChange={(event) => setText(event.target.value)}
                  ></Textarea>
                </Field>
                <div className="resource-form-footer">
                  <Button type="submit" disabled={!title.trim() || !text.trim()} variant="default">
                    {task.busy ? (
                      <LoaderCircle size={16} className="animate-spin" />
                    ) : (
                      <Clipboard size={16} />
                    )}
                    {t('addAndIndex')}
                  </Button>
                </div>
              </FieldSet>
            </form>
          ) : (
            <>
              <input
                type="file"
                multiple
                accept={knowledgeTextExtensions}
                hidden
                ref={input}
                onChange={(event) => {
                  const files = Array.from(event.target.files || []);
                  event.target.value = '';
                  setItems((current) => [
                    ...current,
                    ...files.map((file) => ({ id: crypto.randomUUID(), file, status: 'queued' as const })),
                  ]);
                }}
              />
              <Button
                type="button"
                disabled={!!task.busy}
                onClick={() => input.current?.click()}
                variant="outline"
              >
                <Plus size={16} />
                {t('chooseFiles')}
              </Button>
              <div className="knowledge-upload-list">
                {items.map((item) => (
                  <div className="resource-row" key={item.id}>
                    <div className="resource-identity">
                      <strong>{item.file.name}</strong>
                      <small>
                        {t('uploadStates.' + item.status)}
                        {item.chunks !== undefined ? ` · ${t('chunkCount', { count: item.chunks })}` : ''}
                      </small>
                      {item.error ? <span className="error-text">{item.error}</span> : null}
                    </div>
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            aria-label={t('removeFile')}
                            disabled={!!task.busy}
                            onClick={() => {
                              if (item.attachmentId && temporary.current.has(item.attachmentId)) {
                                temporary.current.delete(item.attachmentId);
                                void chatApi.deleteAttachment(item.attachmentId).catch(() => undefined);
                              }
                              setItems((current) => current.filter((value) => value.id !== item.id));
                            }}
                          />
                        }
                      >
                        <X size={16} />
                      </TooltipTrigger>
                      <TooltipContent>{t('removeFile')}</TooltipContent>
                    </Tooltip>
                  </div>
                ))}
              </div>
              <div className="resource-form-footer">
                <Button
                  type="button"
                  disabled={!!task.busy || !items.some((item) => item.status !== 'indexed')}
                  onClick={() => void upload()}
                  variant="default"
                >
                  {task.busy ? (
                    <LoaderCircle size={16} className="animate-spin" />
                  ) : items.some((item) => item.status === 'failed') ? (
                    <RefreshCw size={16} />
                  ) : (
                    <Upload size={16} />
                  )}
                  {t(items.some((item) => item.status === 'failed') ? 'retryFailed' : 'addAndIndex')}
                </Button>
              </div>
            </>
          )}
        </div>
      </DialogContent>
      {confirmation}
    </Dialog>
  );
}
