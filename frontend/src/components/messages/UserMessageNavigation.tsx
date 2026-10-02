import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useMessageScroller, useMessageScrollerVisibility } from '@/components/ui/message-scroller';
import type { Message } from '../../types/messages';
import { messagePreview } from './messageContent';

export function UserMessageNavigation({ messages }: { messages: Message[] }) {
  const { t } = useTranslation('chat');
  const { currentAnchorId, visibleMessageIds } = useMessageScrollerVisibility();
  const { scrollToMessage } = useMessageScroller();
  const rail = useRef<HTMLElement>(null);
  const activeId = messages.some((message) => message.message_id === currentAnchorId)
    ? currentAnchorId
    : messages.find((message) => visibleMessageIds.includes(message.message_id))?.message_id;
  const activeIndex = messages.findIndex((message) => message.message_id === activeId);

  useEffect(() => {
    const container = rail.current;
    const active = container?.querySelector<HTMLElement>('[aria-current="step"]');
    if (!container || !active) return;
    const outer = container.getBoundingClientRect();
    const inner = active.getBoundingClientRect();
    if (inner.top < outer.top) container.scrollTop += inner.top - outer.top;
    else if (inner.bottom > outer.bottom) container.scrollTop += inner.bottom - outer.bottom;
  }, [activeId]);

  if (messages.length < 2) return null;
  return (
    <nav ref={rail} className="user-message-navigation" aria-label={t('userMessageNavigation')}>
      {messages.map((message, index) => {
        const summary = messagePreview(message) || t('userMessageNumber', { number: index + 1 });
        return (
          <Tooltip key={message.message_id}>
            <TooltipTrigger render={
              <Button variant="ghost" size="icon" className="user-message-tick h-2 w-11 justify-start pl-[10px] pointer-coarse:min-h-2"
                aria-label={t('jumpToUserMessage', { number: index + 1, summary })}
                aria-current={message.message_id === activeId ? 'step' : undefined}
                data-adjacent={activeIndex >= 0 && Math.abs(index - activeIndex) === 1 ? '' : undefined}
                onClick={() => scrollToMessage(message.message_id, {
                  align: 'start',
                  behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
                })} />
            }><span aria-hidden="true" /></TooltipTrigger>
            <TooltipContent side="right" className="max-w-64 break-words">{summary}</TooltipContent>
          </Tooltip>
        );
      })}
    </nav>
  );
}
