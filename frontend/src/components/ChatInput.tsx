import { Paperclip, Send, Square } from 'lucide-react';
import { useRef, useState } from 'react';
import { api } from '../api/client';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { Attachment } from '../types';

export function ChatInput() {
  const draft = useWorkbenchStore((state) => state.composerDraftText);
  const setDraft = useWorkbenchStore((state) => state.setComposerDraftText);
  const send = useWorkbenchStore((state) => state.sendMessage);
  const cancelRun = useWorkbenchStore((state) => state.cancelRun);
  const sending = useWorkbenchStore((state) => state.sending);
  const session = useWorkbenchStore((state) => state.currentSession);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  async function submit() {
    if (sending || uploading || (!draft.trim() && attachments.length === 0)) return;
    await send(draft, attachments);
    setDraft('');
    setAttachments([]);
  }

  async function chooseFiles(event: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || []);
    event.target.value = '';
    if (!files.length) return;
    setUploading(true);
    try {
      const uploaded = await Promise.all(files.map((file) => api.uploadAttachment(file)));
      setAttachments((current) => [...current, ...uploaded]);
    } finally {
      setUploading(false);
    }
  }

  const activeRun = useWorkbenchStore((state) => state.runs.find((run) => run.run_id === session?.waiting_run_id));
  return (
    <div className="composer-wrap">
      {attachments.length ? (
        <div className="attachment-strip">
          {attachments.map((item) => <span key={item.id} className="attachment-chip">{item.name || item.filename || item.id}<button type="button" onClick={() => setAttachments((all) => all.filter((value) => value.id !== item.id))} aria-label="Remove">×</button></span>)}
        </div>
      ) : null}
      {session?.waiting_run_id ? <div className="waiting-banner">This run is waiting for your reply. Your next message will resume it.</div> : null}
      <div className="composer">
        <input ref={fileRef} type="file" multiple hidden onChange={(event) => void chooseFiles(event)} />
        <button className="icon-button" type="button" title="Attach file" aria-label="Attach file" disabled={sending || uploading} onClick={() => fileRef.current?.click()}><Paperclip size={18} /></button>
        <textarea
          value={draft}
          rows={1}
          placeholder="Message the chat… Prefixes are sent as ordinary text."
          onChange={(event) => setDraft(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit(); }
          }}
          disabled={uploading}
        />
        {sending && activeRun ? <button className="icon-button danger" type="button" title="Cancel" aria-label="Cancel" onClick={() => void cancelRun(activeRun.run_id)}><Square size={16} /></button> : <button className="send-button" type="button" disabled={uploading || (!draft.trim() && attachments.length === 0)} onClick={() => void submit()}><Send size={17} /></button>}
      </div>
      <small className="composer-hint">Enter to send · Shift+Enter for a new line</small>
    </div>
  );
}
