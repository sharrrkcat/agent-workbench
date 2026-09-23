import { UserRound } from 'lucide-react';
import type { ReactNode } from 'react';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Message, MessageAvatar, MessageContent, MessageHeader } from '@/components/ui/message';
import { cn } from '@/lib/utils';
import { API_BASE_URL, resolveAttachmentUrlFromBase } from '../../api/url';

export function MessageFrame({
  role,
  name,
  avatarId,
  createdAt,
  messageId,
  runId,
  children,
}: {
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
    <Message
      align={role === 'user' ? 'end' : 'start'}
      className={cn('message-row', role)}
      data-message-id={messageId}
      data-run-id={runId}
    >
      <MessageAvatar className="message-avatar self-start">
        <Avatar>
          {avatarId ? (
            <AvatarImage
              src={resolveAttachmentUrlFromBase(API_BASE_URL, `local://attachments/${avatarId}`)}
              alt={name}
            />
          ) : null}
          <AvatarFallback>
            <UserRound />
          </AvatarFallback>
        </Avatar>
      </MessageAvatar>
      <MessageContent className="message-stack">
        <MessageHeader className="message-meta gap-2 px-0">
          <strong>{name}</strong>
          <time dateTime={createdAt}>
            {Number.isNaN(date.getTime())
              ? ''
              : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </time>
        </MessageHeader>
        {children}
      </MessageContent>
    </Message>
  );
}
