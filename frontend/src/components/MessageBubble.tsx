import { useTranslation } from 'react-i18next';
import { useState } from 'react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { Message } from '../types/messages';
import { MessageFrame } from './messages/MessageFrame';
import { messageText } from './messages/messageContent';

import { MessageParts } from './messages/MessageParts';
import { MessageActions } from './messages/MessageActions';

export function MessageBubble({ message }: { message: Message }) {
  const { t } = useTranslation('personas');
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(messageText(message));
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
    <MessageFrame role={message.role} name={isUser ? t('you') : message.speaker_name || t(message.role === 'assistant' ? 'assistant' : 'system')}
      avatarId={avatarId} createdAt={message.created_at} messageId={message.message_id}>
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
        {isUser ? <MessageActions
          message={message}
          editing={editing}
          busy={busy}
          onEdit={() => setEditing(true)}
          onSave={saveEdit}
          onCancel={() => setEditing(false)}
        /> : null}
    </MessageFrame>
  );
}
