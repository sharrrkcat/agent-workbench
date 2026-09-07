import { UserRound } from 'lucide-react';
import type { ReactNode } from 'react';
import { API_BASE_URL, resolveAttachmentUrlFromBase } from '../../api/url';

export function MessageFrame({ role, name, avatarId, createdAt, messageId, runId, children }: {
  role: string;
  name: string;
  avatarId?: string | null;
  createdAt: string;
  messageId?: string;
  runId?: string;
  children: ReactNode;
}) {
  const date = new Date(createdAt);
  return (
    <article className={`message-row ${role}`} data-message-id={messageId} data-run-id={runId}>
      <div className="message-avatar">
        {avatarId ? <img src={resolveAttachmentUrlFromBase(API_BASE_URL, `local://attachments/${avatarId}`)} alt={name} /> : <UserRound size={17} />}
      </div>
      <div className="message-stack">
        <div className="message-meta">
          <strong>{name}</strong>
          <time dateTime={createdAt}>{Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>
        </div>
        {children}
      </div>
    </article>
  );
}
