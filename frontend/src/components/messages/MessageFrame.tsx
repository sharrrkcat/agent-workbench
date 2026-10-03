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
  messageNumber,
  children,
}: {
  role: string;
  name: string;
  avatarId?: string | null;
  createdAt: string;
  messageId?: string;
  runId?: string;
  messageNumber?: number;
  children: ReactNode;
}) {
  const date = new Date(createdAt);
  return (
    <Message
      align={role === 'user' ? 'end' : 'start'}
      className={cn('message-row w-auto', role)}
      data-message-id={messageId}
      data-run-id={runId}
    >
      <MessageContent className="message-stack">
        <MessageHeader className="message-meta gap-2 px-0">
          <MessageAvatar className="message-avatar">
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
          {role !== 'user' ? <strong>{name}</strong> : null}
          <time dateTime={createdAt}>
            {Number.isNaN(date.getTime())
              ? ''
              : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </time>
          {messageNumber != null ? <span className="message-number text-muted-foreground whitespace-nowrap tabular-nums">#{messageNumber}</span> : null}
          {role === 'user' ? <strong>{name}</strong> : null}
        </MessageHeader>
        {children}
      </MessageContent>
    </Message>
  );
}
