import { MessageSquareQuote, Pencil, RefreshCw, Trash2, UserRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { Message, MessagePart } from '../types';
import { resolveAttachmentUrlFromBase } from '../api/url';
import { API_BASE_URL } from '../api/client';

export type FilePreview = { name: string; content: string; mimeType?: string };

export function MessageBubble({ message }: { message: Message }) {
  const { t } = useTranslation('personas');
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(textOf(message));
  const [busy, setBusy] = useState(false);
  const deleteMessage = useWorkbenchStore((state) => state.deleteMessage);
  const retryMessage = useWorkbenchStore((state) => state.retryMessage);
  const selectContext = useWorkbenchStore((state) => state.setSourceMessageId);
  const selectedContext = useWorkbenchStore((state) => state.sourceMessageId);
  const acceptsSelection = useWorkbenchStore((state) => state.currentSession?.effective.context_policy.mode === 'selected_message');
  const active = useWorkbenchStore((state) => state.runs.some((r) => ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(r.status)));
  const avatarId = typeof message.metadata?.speaker_avatar_attachment_id === 'string' ? message.metadata.speaker_avatar_attachment_id : null;
  const isUser = message.role === 'user';
  const streaming = message.metadata?.streaming === true;

  async function saveEdit() {
    setBusy(true);
    try { await useWorkbenchStore.getState().editMessage(message.message_id, value); setEditing(false); } finally { setBusy(false); }
  }

  return (
    <article className={`message-row ${message.role}`} data-message-id={message.message_id}>
      <div className="message-avatar">{avatarId ? <img src={resolveAttachmentUrlFromBase(API_BASE_URL, `local://attachments/${avatarId}`)} alt={message.speaker_name || ''} /> : <UserRound size={17} />}</div>
      <div className="message-stack">
        <div className="message-meta"><strong>{isUser ? t('you') : message.speaker_name || t(message.role === 'assistant' ? 'assistant' : 'system')}</strong><time>{formatTime(message.created_at)}</time></div>
        <div className="message">
          {editing ? <textarea value={value} onChange={(event) => setValue(event.currentTarget.value)} rows={Math.max(3, value.split('\n').length)} /> : <MessageParts parts={message.parts} />}
          {streaming ? <span className="streaming-cursor" aria-hidden="true" /> : null}
        </div>
        <div className="message-actions">
          {isUser && !editing ? <button type="button" disabled={active} onClick={() => setEditing(true)} title={t('editMessage')} aria-label={t('editMessage')}><Pencil size={14} /></button> : null}
          {isUser && editing ? <><button type="button" onClick={() => void saveEdit()} disabled={busy || active}>{t('save')}</button><button type="button" onClick={() => setEditing(false)}>{t('cancel')}</button></> : null}
          {!isUser && message.role === 'assistant' && !message.parts.some((p) => p.type === 'tool_call') ? <button type="button" disabled={streaming || active} onClick={() => void retryMessage(message.message_id)} title={t('retry')} aria-label={t('retry')}><RefreshCw size={14} /></button> : null}
          {acceptsSelection && ['user', 'assistant', 'tool'].includes(message.role) && !message.metadata?.event_type && !message.parts.some((p) => p.type === 'error') ? <button type="button" disabled={streaming} aria-pressed={selectedContext === message.message_id} title={t('selectContext')} aria-label={t('selectContext')} onClick={() => selectContext(selectedContext === message.message_id ? null : message.message_id)}><MessageSquareQuote size={14} /></button> : null}
          <button type="button" disabled={streaming || active} onClick={() => { if (window.confirm(t('deleteMessageConfirm'))) void deleteMessage(message.message_id); }} title={t('deleteMessage')} aria-label={t('deleteMessage')}><Trash2 size={14} /></button>
        </div>
      </div>
    </article>
  );
}

export function MessageParts({ parts }: { parts: MessagePart[] }) {
  return <div className="message-parts">{parts.map((part) => <Part key={part.id} part={part} />)}</div>;
}

function Part({ part }: { part: MessagePart }) {
  const { t } = useTranslation('runs');
  if (part.type === 'text') return part.format === 'plain' ? <p className="part-text">{part.text}</p> : <div className="part-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{part.text}</ReactMarkdown></div>;
  if (part.type === 'json') return <pre className="part-json">{JSON.stringify(part.data, null, 2)}</pre>;
  if (part.type === 'tool_call') return <details className="part-tool" open><summary>{t('toolCall')} · {part.tool_name}</summary><pre className="part-json">{JSON.stringify(part.arguments, null, 2)}</pre></details>;
  if (part.type === 'tool_result') return <details className={`part-tool tool-${part.status}`} open><summary>{part.tool_name} · {t(`toolStatus.${part.status}`)}</summary>{part.error_message ? <p className="part-error">{part.error_code ? `${part.error_code}: ` : ''}{part.error_message}</p> : null}{part.data !== undefined ? <pre className="part-json">{JSON.stringify(part.data, null, 2)}</pre> : null}{part.truncated ? <small>{t('outputTruncated')}</small> : null}</details>;
  if (part.type === 'file') return <pre className="part-file">{part.content || part.filename || part.attachment_id || 'File'}</pre>;
  if (part.type === 'image') { const url = part.url || (part.attachment_id ? resolveAttachmentUrlFromBase(API_BASE_URL, `local://attachments/${part.attachment_id}`) : ''); return url ? <figure className="part-image"><img src={url} alt={part.alt || part.title || ''} /><figcaption>{part.caption}</figcaption></figure> : null; }
  if (part.type === 'media_group') return <div className="part-gallery">{part.items.map((item, index) => { const url = item.url || (item.attachment_id ? resolveAttachmentUrlFromBase(API_BASE_URL, `local://attachments/${item.attachment_id}`) : ''); return url ? <img key={`${url}-${index}`} src={url} alt={item.alt || ''} /> : null; })}</div>;
  if (part.type === 'audio') return <audio controls src={part.url} />;
  if (part.type === 'video') return <video controls src={part.url} poster={part.poster_url} />;
  if (part.type === 'error') return <div className="part-error">{part.code ? `${part.code}: ` : ''}{part.message}</div>;
  return <div className={`part-notice ${part.level || 'info'}`}>{part.text}</div>;
}

function textOf(message: Message): string { return message.parts.filter((part): part is Extract<MessagePart, { type: 'text' }> => part.type === 'text').map((part) => part.text).join('\n\n'); }
function formatTime(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
