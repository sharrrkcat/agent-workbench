import type { ComponentProps } from 'react';
import { MessageScroller, MessageScrollerContent, MessageScrollerViewport } from '@/components/ui/message-scroller';
import { cn } from '@/lib/utils';

export function ConversationScroller({ className, ...props }: ComponentProps<typeof MessageScroller>) {
  return <MessageScroller {...props} className={cn('chat-scroll-container h-auto flex-1', className)} />;
}

export function ConversationViewport({ className, ...props }: ComponentProps<typeof MessageScrollerViewport>) {
  return <MessageScrollerViewport {...props} className={cn('chat-view', className)} style={{ scrollbarGutter: 'stable both-edges', ...props.style }} />;
}

export function ConversationContent({ className, ...props }: ComponentProps<typeof MessageScrollerContent>) {
  return <MessageScrollerContent {...props} className={cn('conversation-content', className)} />;
}
