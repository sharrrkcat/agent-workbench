import { useLayoutEffect, useRef, useState } from 'react';
import { chatApi } from '../api/chat';
import { useCogitaStore } from '../store/useCogitaStore';
import type { ComposerAttachment as Upload } from '../store/cogita/messageQueue';

export function useComposerAttachments(sessionEpoch: number) {
  const [localItems, setItems] = useState<Upload[]>([]);
  const sessionId = useCogitaStore((state) => state.currentSession?.session_id);
  const editing = useCogitaStore((state) => state.currentSession ? state.messageQueues[state.currentSession.session_id]?.editing : null);
  const items = editing?.attachments ?? localItems;
  const generation = useRef(0);
  const previews = useRef(new Set<string>());

  function releasePreviews() {
    for (const url of previews.current) URL.revokeObjectURL(url);
    previews.current.clear();
  }

  useLayoutEffect(() => {
    setItems([]);
    return () => { generation.current++; releasePreviews(); };
  }, [sessionEpoch]);

  async function upload(files: File[]) {
    const epoch = generation.current;
    const edit = editing && sessionId ? { sessionId, id: editing.id } : null;
    const update = (change: (current: Upload[]) => Upload[]) => {
      if (edit) useCogitaStore.getState().setQueuedEditAttachments(edit.sessionId, edit.id, change);
      else if (epoch === generation.current) setItems(change);
    };
    const batch: Upload[] = files.map((file) => {
      // Queue edits survive unmounts; use the uploaded URI instead of owning a blob URL there.
      const isImage = file.type.startsWith('image/');
      const preview = isImage && !edit ? URL.createObjectURL(file) : null;
      if (preview) previews.current.add(preview);
      return { id: crypto.randomUUID(), name: file.name, size: file.size, mime_type: file.type,
        type: isImage ? 'image' : 'file', preview, status: 'uploading' };
    });
    update((current) => [...current, ...batch]);
    await Promise.all(files.map(async (file, index) => {
      let result: Partial<Upload>;
      try {
        const attachment = await chatApi.uploadAttachment(file);
        result = { attachment, size: attachment.size, mime_type: attachment.mime_type, type: attachment.type,
          uri: attachment.uri || `local://attachments/${attachment.id}`, status: 'ready' };
      } catch (error) {
        result = { error: error instanceof Error ? error.message : String(error), status: 'error' };
      }
      update((current) => current.map((item) => item.id === batch[index].id ? { ...item, ...result } : item));
    }));
  }

  function remove(id: string) {
    const item = items.find((value) => value.id === id);
    if (item?.preview) { URL.revokeObjectURL(item.preview); previews.current.delete(item.preview); }
    if (editing && sessionId) useCogitaStore.getState().setQueuedEditAttachments(sessionId, editing.id,
      (current) => current.filter((value) => value.id !== id));
    else setItems((current) => current.filter((value) => value.id !== id));
  }

  function take() {
    generation.current++;
    setItems([]);
    return items;
  }

  function discard(batch: Upload[]) {
    for (const item of batch) {
      if (item.preview) { URL.revokeObjectURL(item.preview); previews.current.delete(item.preview); }
    }
  }

  return { items, upload, remove, take, discard, restore: setItems, uploading: items.some((item) => item.status === 'uploading'),
    uploadFailed: items.some((item) => item.status === 'error'),
    attachments: items.flatMap((item) => item.attachment ? [item.attachment] : []) };
}
