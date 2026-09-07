import { Paperclip, Send, Square, X } from 'lucide-react';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { chatApi } from '../api/chat';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { Attachment } from '../types/messages';
import { contextMessageLabel, isContextMessage } from './messages/messageContent';

export function ChatInput() {
  const { t } = useTranslation('personas');
  const draft = useWorkbenchStore((state) => state.composerDraftText);
  const setDraft = useWorkbenchStore((state) => state.setComposerDraftText);
  const send = useWorkbenchStore((state) => state.sendMessage);
  const cancelRun = useWorkbenchStore((state) => state.cancelRun);
  const sending = useWorkbenchStore((state) => state.sending);
  const mutatingHistory = useWorkbenchStore((state) => state.mutatingHistory);
  const session = useWorkbenchStore((state) => state.currentSession);
  const messages = useWorkbenchStore((state) => state.messages);
  const sourceMessageId = useWorkbenchStore((state) => state.sourceMessageId);
  const selectSource = useWorkbenchStore((state) => state.setSourceMessageId);
  const setError = useWorkbenchStore((state) => state.setError);
  const activeRun = useWorkbenchStore((state) => [...state.runs].reverse().find((r) => ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(r.status)));
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const contextRequired = session?.effective.context_policy.mode === 'selected_message';
  const eligible = messages.filter(isContextMessage);
  const hasSource = !!sourceMessageId && eligible.some((m) => m.message_id === sourceMessageId);

  async function submit() {
    if (sending || mutatingHistory || uploading || activeRun || (contextRequired && !hasSource) || (!draft.trim() && attachments.length === 0)) return;
    const result = await send(draft, attachments);
    if (result) { setDraft(''); setAttachments([]); }
  }

  async function chooseFiles(event: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || []);
    event.target.value = '';
    if (!files.length) return;
    setUploading(true);
    try {
      const uploaded = await Promise.all(files.map((file) => chatApi.uploadAttachment(file)));
      setAttachments((current) => [...current, ...uploaded]);
    } catch (e) {
      setError(String(e));
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="composer-wrap">
      {attachments.length ? (
        <div className="attachment-strip">
          {attachments.map((item) => <span key={item.id} className="attachment-chip">{item.name || item.filename || item.id}<button type="button" onClick={() => setAttachments((all) => all.filter((value) => value.id !== item.id))} aria-label={t('remove')}><X size={13} /></button></span>)}
        </div>
      ) : null}
      {session?.waiting_run_id ? <div className="waiting-banner">{t('waiting')}</div> : null}
      {contextRequired ? <label className="composer-context"><span>{t('selectedContext')}</span><select value={hasSource ? sourceMessageId : ''} onChange={(e) => selectSource(e.target.value || null)}><option value="">{t('chooseContext')}</option>{eligible.map((m) => <option key={m.message_id} value={m.message_id}>{m.speaker_name || m.role}: {contextMessageLabel(m)}</option>)}</select></label> : null}
      <div className="composer">
        <input ref={fileRef} type="file" multiple hidden onChange={(event) => void chooseFiles(event)} />
        <button className="icon-button" type="button" title={t('attach')} aria-label={t('attach')} disabled={sending || uploading} onClick={() => fileRef.current?.click()}><Paperclip size={18} /></button>
        <textarea
          value={draft}
          rows={1}
          placeholder={t('messagePlaceholder', { name: session?.effective.persona_name || t('assistant') })}
          aria-label={t('messagePlaceholder', { name: session?.effective.persona_name || t('assistant') })}
          onChange={(event) => setDraft(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); }
          }}
          disabled={uploading}
        />
        {activeRun ? <button className="icon-button danger" type="button" disabled={activeRun.status === 'CANCELLING'} title={t('cancel')} aria-label={t('cancel')} onClick={() => void cancelRun(activeRun.run_id)}><Square size={16} /></button> : <button className="send-button" type="button" aria-label={t('send')} disabled={sending || mutatingHistory || uploading || (contextRequired && !hasSource) || (!draft.trim() && attachments.length === 0)} onClick={() => void submit()}><Send size={17} /></button>}
      </div>
    </div>
  );
}
