import { Pencil, RefreshCw, Trash2 } from 'lucide-react';
import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api } from '../api/client';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { Message, MessagePart } from '../types';
import { resolveAttachmentUrlFromBase } from '../api/url';
import { API_BASE_URL } from '../api/client';

export type FilePreview = { name: string; content: string; mimeType?: string };

export function MessageBubble({ message }: { message: Message }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(textOf(message));
  const [busy, setBusy] = useState(false);
  const deleteMessage = useWorkbenchStore((state) => state.deleteMessage);
  const retryMessage = useWorkbenchStore((state) => state.retryMessage);
  const isUser = message.role === 'user';

  async function saveEdit() {
    setBusy(true);
    try { await useWorkbenchStore.getState().editMessage(message.message_id, value); setEditing(false); } finally { setBusy(false); }
  }

  return (
    <article className={`message-row ${message.role}`} data-message-id={message.message_id}>
      <div className="message-avatar">{isUser ? 'U' : message.role === 'assistant' ? 'A' : '•'}</div>
      <div className="message-stack">
        <div className="message-meta"><strong>{message.speaker_name || (isUser ? 'You' : message.role === 'assistant' ? 'Assistant' : 'System')}</strong><time>{formatTime(message.created_at)}</time></div>
        <div className="message">
          {editing ? <textarea value={value} onChange={(event) => setValue(event.currentTarget.value)} rows={Math.max(3, value.split('\n').length)} /> : <MessageParts parts={message.parts} />}
        </div>
        <div className="message-actions">
          {isUser && !editing ? <button type="button" onClick={() => setEditing(true)} title="Edit"><Pencil size={14} /></button> : null}
          {isUser && editing ? <><button type="button" onClick={() => void saveEdit()} disabled={busy}>Save</button><button type="button" onClick={() => setEditing(false)}>Cancel</button></> : null}
          {!isUser && message.role === 'assistant' ? <button type="button" onClick={() => void retryMessage(message.message_id)} title="Retry"><RefreshCw size={14} /></button> : null}
          <button type="button" onClick={() => { if (window.confirm('Delete this message?')) void deleteMessage(message.message_id); }} title="Delete"><Trash2 size={14} /></button>
        </div>
      </div>
    </article>
  );
}

export function MessageParts({ parts }: { parts: MessagePart[] }) {
  return <div className="message-parts">{parts.map((part) => <Part key={part.id} part={part} />)}</div>;
}

function Part({ part }: { part: MessagePart }) {
  if (part.type === 'text') return part.format === 'plain' ? <p className="part-text">{part.text}</p> : <div className="part-markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{part.text}</ReactMarkdown></div>;
  if (part.type === 'json') return <pre className="part-json">{JSON.stringify(part.data, null, 2)}</pre>;
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
