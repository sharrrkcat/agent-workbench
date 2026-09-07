import { UserRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useState } from 'react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { Message, MessagePart } from '../types/messages';
import { resolveAttachmentUrlFromBase } from '../api/url';
import { API_BASE_URL } from '../api/url';

import { MessageParts } from './messages/MessageParts';
import { MessageActions } from './messages/MessageActions';

export function MessageBubble({ message }: { message: Message }) {
  const { t } = useTranslation('personas');
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(textOf(message));
  const [busy, setBusy] = useState(false);
  const avatarId =
    typeof message.metadata?.speaker_avatar_attachment_id === 'string'
      ? message.metadata.speaker_avatar_attachment_id
      : null;
  const isUser = message.role === 'user';
  const streaming = message.metadata?.streaming === true;

  async function saveEdit() {
    setBusy(true);
    try {
      await useWorkbenchStore.getState().editMessage(message.message_id, value);
      setEditing(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className={`message-row ${message.role}`} data-message-id={message.message_id}>
      <div className="message-avatar">
        {avatarId ? (
          <img
            src={resolveAttachmentUrlFromBase(API_BASE_URL, `local://attachments/${avatarId}`)}
            alt={message.speaker_name || ''}
          />
        ) : (
          <UserRound size={17} />
        )}
      </div>
      <div className="message-stack">
        <div className="message-meta">
          <strong>
            {isUser ? t('you') : message.speaker_name || t(message.role === 'assistant' ? 'assistant' : 'system')}
          </strong>
          <time>{formatTime(message.created_at)}</time>
        </div>
        <div className="message">
          {editing ? (
            <textarea
              value={value}
              onChange={(event) => setValue(event.currentTarget.value)}
              rows={Math.max(3, value.split('\n').length)}
            />
          ) : (
            <MessageParts parts={message.parts} />
          )}
          {streaming ? <span className="streaming-cursor" aria-hidden="true" /> : null}
        </div>
        <MessageActions
          message={message}
          editing={editing}
          busy={busy}
          onEdit={() => setEditing(true)}
          onSave={saveEdit}
          onCancel={() => setEditing(false)}
        />
      </div>
    </article>
  );
}

function textOf(message: Message): string {
  return message.parts
    .filter((part): part is Extract<MessagePart, { type: 'text' }> => part.type === 'text')
    .map((part) => part.text)
    .join('\n\n');
}
function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
