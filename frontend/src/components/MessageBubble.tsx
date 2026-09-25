import { Textarea } from '@/components/ui/textarea';
import { Bubble, BubbleContent } from '@/components/ui/bubble';
import { useTranslation } from 'react-i18next';
import { useState } from 'react';
import { useCogitaStore } from '../store/useCogitaStore';
import type { Message } from '../types/messages';
import { MessageFrame } from './messages/MessageFrame';
import { messageImages, messageText } from './messages/messageContent';
import { MessageImages } from './messages/MessageImages';

import { MessageParts } from './messages/MessageParts';
import { MessageActions } from './messages/MessageActions';

export function MessageBubble({ message }: { message: Message }) {
  const { t } = useTranslation('personas');
  const userPersona = useCogitaStore((s) => s.currentSession?.user_persona);
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
      await useCogitaStore.getState().editMessage(message.message_id, value);
      setEditing(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <MessageFrame
      role={message.role}
      name={
        isUser ? userPersona?.name || '' : message.speaker_name || t(message.role === 'assistant' ? 'assistant' : 'system')
      }
      avatarId={isUser ? userPersona?.avatar_attachment_id : avatarId}
      createdAt={message.created_at}
      messageId={message.message_id}
    >
      <Bubble
        variant={isUser ? 'secondary' : 'ghost'}
        align={isUser ? 'end' : 'start'}
        className={editing ? 'w-full max-w-full' : undefined}
      >
        <BubbleContent className={editing ? 'w-full' : undefined}>
          <div className="message">
            {editing ? (
              <Textarea
                value={value}
                onChange={(event) => setValue(event.currentTarget.value)}
                rows={Math.max(3, value.split('\n').length)}
              ></Textarea>
            ) : (
              <MessageParts parts={message.parts} />
            )}
            {messageImages(message).length ? <MessageImages attachments={messageImages(message)} /> : null}
            {streaming ? <span className="streaming-cursor" aria-hidden="true" /> : null}
          </div>
        </BubbleContent>
      </Bubble>
      {isUser ? (
        <MessageActions
          message={message}
          editing={editing}
          busy={busy}
          onEdit={() => setEditing(true)}
          onSave={saveEdit}
          onCancel={() => setEditing(false)}
        />
      ) : null}
    </MessageFrame>
  );
}
