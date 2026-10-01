import { Textarea } from '@/components/ui/textarea';
import { Bubble, BubbleContent } from '@/components/ui/bubble';
import { cn } from '@/lib/utils';
import { useTranslation } from 'react-i18next';
import { useState } from 'react';
import { useCogitaStore } from '../store/useCogitaStore';
import type { Message } from '../types/messages';
import { MessageFrame } from './messages/MessageFrame';
import { messageAttachments, messageText } from './messages/messageContent';
import { ChatAttachments } from './messages/ChatAttachments';

import { MessageParts } from './messages/MessageParts';
import { MessageActions } from './messages/MessageActions';
import { usePersonaIdentity } from '../hooks/usePersonaIdentity';

export function MessageBubble({ message, animate = false }: { message: Message; animate?: boolean }) {
  const { t } = useTranslation('personas');
  const userPersona = useCogitaStore((s) => s.currentSession?.user_persona);
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(messageText(message));
  const [attachments, setAttachments] = useState(messageAttachments(message));
  const [busy, setBusy] = useState(false);
  const identity = usePersonaIdentity()(message.speaker_id);
  const isUser = message.role === 'user';
  const streaming = message.metadata?.streaming === true;
  const shownAttachments = editing || busy ? attachments : messageAttachments(message);
  const parts = busy ? (value.trim() ? [{ id: 'pending-edit', type: 'text' as const, format: 'plain' as const, text: value }] : []) : message.parts;
  const canSave = !!value.trim() || attachments.length > 0;

  async function saveEdit() {
    if (!canSave) return;
    setBusy(true);
    setEditing(false);
    try {
      const saved = await useCogitaStore.getState().editMessage(message.message_id, value, attachments.map((item) => item.id));
      if (!saved) setEditing(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <MessageFrame
      role={message.role}
      name={
        isUser ? userPersona?.name || '' : message.role === 'assistant' ? identity.name : message.speaker_name || t('system')
      }
      avatarId={isUser ? userPersona?.avatar_attachment_id : message.role === 'assistant' ? identity.avatar_attachment_id : null}
      createdAt={message.created_at}
      messageId={message.message_id}
    >
      <ChatAttachments items={shownAttachments.filter((item) => item.type !== 'image')}
        onRemove={editing ? (id) => setAttachments((items) => items.filter((item) => item.id !== id)) : undefined} />
      {editing || parts.length || streaming ? <Bubble
        variant={isUser ? 'secondary' : 'ghost'}
        align={isUser ? 'end' : 'start'}
        className={cn(editing && 'w-full max-w-full', isUser && animate && 'user-message-enter')}
      >
        <BubbleContent className={cn(editing && 'w-full', isUser && 'rounded-[24px]')}>
          <div className="message">
            {editing ? (
              <Textarea
                aria-label={t('messageText')}
                value={value}
                onChange={(event) => setValue(event.currentTarget.value)}
                rows={Math.max(3, value.split('\n').length)}
              ></Textarea>
            ) : (
              <MessageParts parts={parts} />
            )}
            {streaming ? <span className="streaming-cursor" aria-hidden="true" /> : null}
          </div>
        </BubbleContent>
      </Bubble> : null}
      <ChatAttachments items={shownAttachments.filter((item) => item.type === 'image')}
        onRemove={editing ? (id) => setAttachments((items) => items.filter((item) => item.id !== id)) : undefined} />
      {isUser ? message.metadata?.request_warnings?.codes.map((code) => (
        <p key={code} className="message-request-warning" role="status">
          {t(`chat:requestWarnings.${code}`)}
        </p>
      )) : null}
      {isUser ? (
        <MessageActions
          message={message}
          editing={editing}
          busy={busy}
          canSave={canSave}
          onEdit={() => { setValue(messageText(message)); setAttachments(messageAttachments(message)); setEditing(true); }}
          onSave={saveEdit}
          onCancel={() => setEditing(false)}
        />
      ) : null}
    </MessageFrame>
  );
}
