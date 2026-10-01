import { useLayoutEffect, useRef, useState } from 'react';
import { chatApi } from '../api/chat';
import type { Attachment } from '../types/messages';
import type { ChatAttachment } from '../components/messages/ChatAttachments';

type Upload = ChatAttachment & {
  status: 'uploading' | 'ready' | 'error';
  attachment?: Attachment;
};

export function useComposerAttachments(sessionEpoch: number) {
  const [items, setItems] = useState<Upload[]>([]);
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
    const batch: Upload[] = files.map((file) => {
      const preview = file.type.startsWith('image/') ? URL.createObjectURL(file) : null;
      if (preview) previews.current.add(preview);
      return { id: crypto.randomUUID(), name: file.name, size: file.size, mime_type: file.type,
        type: preview ? 'image' : 'file', preview, status: 'uploading' };
    });
    setItems((current) => [...current, ...batch]);
    await Promise.all(files.map(async (file, index) => {
      let result: Partial<Upload>;
      try {
        const attachment = await chatApi.uploadAttachment(file);
        result = { attachment, size: attachment.size, mime_type: attachment.mime_type, type: attachment.type, status: 'ready' };
      } catch (error) {
        result = { error: error instanceof Error ? error.message : String(error), status: 'error' };
      }
      if (epoch === generation.current)
        setItems((current) => current.map((item) => item.id === batch[index].id ? { ...item, ...result } : item));
    }));
  }

  function remove(id: string) {
    const item = items.find((value) => value.id === id);
    if (item?.preview) { URL.revokeObjectURL(item.preview); previews.current.delete(item.preview); }
    setItems((current) => current.filter((value) => value.id !== id));
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
    attachments: items.flatMap((item) => item.attachment ? [item.attachment] : []) };
}
