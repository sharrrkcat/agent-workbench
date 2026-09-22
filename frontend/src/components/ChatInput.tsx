import { Paperclip, Send, Square, X } from 'lucide-react';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { useModelsStore } from '../store/useModelsStore';
import { useComposerAttachments } from '../hooks/useComposerAttachments';
import { ImagePreview, type PreviewImage } from './messages/ImagePreview';
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
  const sessionEpoch = useWorkbenchStore((state) => state.sessionEpoch);
  const profiles = useModelsStore((state) => state.profiles);
  const activeRun = useWorkbenchStore((state) => [...state.runs].reverse().find((r) => ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(r.status)));
  const { items, attachments, uploading, upload, remove, clear } = useComposerAttachments(sessionEpoch);
  const [preview, setPreview] = useState<PreviewImage | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const contextRequired = session?.effective.context_policy.mode === 'selected_message';
  const eligible = messages.filter(isContextMessage);
  const hasSource = !!sourceMessageId && eligible.some((m) => m.message_id === sourceMessageId);
  const profile = profiles.find((item) => item.id === session?.model_profile_id);
  const hasImages = attachments.some((item) => item.type === 'image');
  const imageIssue = hasImages && session?.effective.context_policy.include_attachments !== 'explicit'
    ? t('imagesContextDisabled') : hasImages && profile && !profile.capabilities.vision ? t('imagesUnsupported') : '';
  const cannotSend = sending || mutatingHistory || uploading || !!imageIssue || (contextRequired && !hasSource) || (!draft.trim() && attachments.length === 0);

  async function submit() {
    if (cannotSend || activeRun) return;
    const result = await send(draft, attachments);
    if (result && useWorkbenchStore.getState().sessionEpoch === sessionEpoch) { setDraft(''); setPreview(null); clear(); }
  }

  function addFiles(files: File[]) {
    if (files.length && session && !sending && !mutatingHistory) void upload(files);
  }

  return (
    <div className={`composer-wrap${dragging ? ' is-dragging' : ''}`}
      onDragOver={(event) => { if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); setDragging(true); } }}
      onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false); }}
      onDrop={(event) => { event.preventDefault(); setDragging(false); addFiles(Array.from(event.dataTransfer.files)); }}>
      {items.length ? (
        <div className="attachment-strip">
          {items.map((item) => <div key={item.id} className={`attachment-chip upload-${item.status}`}>
            {item.preview ? <button className="attachment-thumbnail" type="button" aria-label={t('previewImage', { name: item.name })}
              onClick={() => setPreview({ src: item.preview!, name: item.name })}><img src={item.preview} alt={item.name} /></button> : null}
            <span className="attachment-details"><span title={item.name}>{item.name}</span>
              {item.status === 'uploading' ? <span role="status">{t('uploading')}</span> : null}
              {item.status === 'error' ? <span role="alert" title={item.error}>{t('uploadFailed')} {item.error}</span> : null}
            </span>
            <button type="button" onClick={() => { setPreview(null); remove(item.id); }} aria-label={t('removeAttachment', { name: item.name })}><X size={14} /></button>
          </div>)}
        </div>
      ) : null}
      {imageIssue ? <p className="composer-warning" role="alert">{imageIssue}</p> : null}
      {session?.waiting_run_id ? <div className="waiting-banner">{t('waiting')}</div> : null}
      {contextRequired ? <label className="composer-context"><span>{t('selectedContext')}</span><select value={hasSource ? sourceMessageId : ''} onChange={(e) => selectSource(e.target.value || null)}><option value="">{t('chooseContext')}</option>{eligible.map((m) => <option key={m.message_id} value={m.message_id}>{m.speaker_name || m.role}: {contextMessageLabel(m)}</option>)}</select></label> : null}
      <div className="composer">
        <input ref={fileRef} type="file" multiple hidden onChange={(event) => { addFiles(Array.from(event.target.files || [])); event.target.value = ''; }} />
        <button className="icon-button" type="button" title={t('attach')} aria-label={t('attach')} disabled={sending || mutatingHistory} onClick={() => fileRef.current?.click()}><Paperclip size={18} /></button>
        <textarea
          value={draft}
          rows={1}
          placeholder={t('messagePlaceholder', { name: session?.effective.persona_name || t('assistant') })}
          aria-label={t('messagePlaceholder', { name: session?.effective.persona_name || t('assistant') })}
          onChange={(event) => setDraft(event.currentTarget.value)}
          onPaste={(event) => { const files = Array.from(event.clipboardData.files); if (files.length) { event.preventDefault(); addFiles(files); } }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); }
          }}
        />
        {activeRun ? <button className="icon-button danger" type="button" disabled={activeRun.status === 'CANCELLING'} title={t('cancel')} aria-label={t('cancel')} onClick={() => void cancelRun(activeRun.run_id)}><Square size={16} /></button> : <button className="send-button" type="button" aria-label={t('send')} disabled={cannotSend} onClick={() => void submit()}><Send size={17} /></button>}
      </div>
      <span className="composer-hint">{dragging ? t('dropFiles') : hasImages && profile?.source?.type === 'local' ? t('localImageLimit') : t('imageInputHint')}</span>
      <ImagePreview image={items.some((item) => item.preview === preview?.src) ? preview : null} onClose={() => setPreview(null)} />
    </div>
  );
}
