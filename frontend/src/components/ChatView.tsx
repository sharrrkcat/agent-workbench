import { ConversationScroller, ConversationViewport, ConversationContent } from './ConversationSurface';
import { useEffect, useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { MessageSquare, ArrowDown } from 'lucide-react';
import {
  MessageScrollerButton,
  MessageScrollerItem,
  MessageScrollerProvider,
  useMessageScroller,
  useMessageScrollerVisibility,
} from '@/components/ui/message-scroller';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { LoadingStatus } from '@/components/ui/loading-status';
import { cn } from '@/lib/utils';
import { MessageBubble } from './MessageBubble';
import { RunReply } from './messages/RunReply';
import { buildConversation } from './messages/turns';
import { messageNumbers } from './messages/messageNumbers';
import { MessageNumbersContext } from './messages/MessageNumbersContext';
import { useCogitaStore } from '../store/useCogitaStore';
import { ResourceLoading } from './settings/resources/ResourceUI';
import { useChatConfiguration } from '../hooks/useChatConfiguration';
import { UserMessageNavigation } from './messages/UserMessageNavigation';
import { useNewUserMessages } from './messages/useNewUserMessages';
import { Button } from '@/components/ui/button';

export function ChatView() {
  const following = useCogitaStore((state) => state.historyFollowing);
  return (
    <MessageScrollerProvider autoScroll={following} scrollEdgeThreshold={32}>
      <Conversation />
    </MessageScrollerProvider>
  );
}

function Conversation() {
  const { t } = useTranslation(['personas', 'chat']);
  const messages = useCogitaStore((state) => state.messages);
  const runs = useCogitaStore((state) => state.runs);
  const currentSession = useCogitaStore((state) => state.currentSession);
  const chatDraft = useCogitaStore((state) => state.chatDraft);
  const configuration = useChatConfiguration();
  const steps = useCogitaStore((state) => state.stepsByRunId);
  const showFullProcessing = useCogitaStore((state) => state.settings?.show_full_processing === true);
  const sending = useCogitaStore((state) => state.sending);
  const loading = useCogitaStore((state) => state.loading);
  const sessionLoad = useCogitaStore((state) => state.sessionLoad);
  const retrySession = useCogitaStore((state) => state.retrySession);
  const { scrollToEnd, scrollToMessage } = useMessageScroller();
  const { visibleMessageIds } = useMessageScrollerVisibility();
  const viewport = useRef<HTMLDivElement>(null);
  const userScrolling = useRef(false);
  const history = useCogitaStore((state) => state.historyWindow);
  const historyLoading = useCogitaStore((state) => state.historyLoading);
  useEffect(() => { if (historyLoading) userScrolling.current = false; }, [historyLoading]);
  const loadHistory = useCogitaStore((state) => state.loadHistory);
  const setHistoryAnchor = useCogitaStore((state) => state.setHistoryAnchor);
  const setHistoryFollowing = useCogitaStore((state) => state.setHistoryFollowing);
  const animatedIds = useNewUserMessages();
  const items = useMemo(
    () => (currentSession ? buildConversation(currentSession.session_id, messages, runs, steps)
      .filter((item) => !history || history.items.some((i) => i.id === item.id)) : []),
    [currentSession?.session_id, messages, runs, steps, history],
  );
  const numbers = useMemo(() => {
    if (!history) return messageNumbers(items);
    const result = new Map(history.items.map((item) => [item.id, item.number]));
    for (const item of items) if (item.kind === 'reply') {
      for (const message of item.reply.messages) result.set(message.message_id, result.get(item.id)!);
    }
    return result;
  }, [items, history]);

  useEffect(() => {
    const anchor = history?.items.find((i) => i.id === visibleMessageIds[0]);
    if (anchor) setHistoryAnchor(anchor.cursor);
  }, [history, visibleMessageIds, setHistoryAnchor]);

  async function page(direction: 'before' | 'after') {
    if (historyLoading) return;
    const container = viewport.current;
    const row = Array.from(container?.querySelectorAll<HTMLElement>('[data-slot="message-scroller-item"][data-message-id]') ?? [])
      .find((node) => node.getBoundingClientRect().bottom > container!.getBoundingClientRect().top);
    const id = row?.dataset.messageId;
    const margin = row && container ? row.getBoundingClientRect().top - container.getBoundingClientRect().top : 0;
    await loadHistory(direction);
    if (id) requestAnimationFrame(() => scrollToMessage(id, { align: 'start', behavior: 'instant', scrollMargin: margin }));
  }

  async function latest() {
    userScrolling.current = false;
    await loadHistory('latest');
    requestAnimationFrame(() => scrollToEnd({ behavior: 'instant' }));
  }

  useEffect(() => {
    if (sending && !history?.has_after) scrollToEnd({ behavior: 'instant' });
  }, [sending, history?.has_after, scrollToEnd]);

  if (sessionLoad && sessionLoad.status !== 'ready') {
    return <div className="chat-view min-h-0 flex-1" aria-busy={sessionLoad.status === 'loading'}>
      <ResourceLoading error={sessionLoad.error || undefined} retry={() => void retrySession()} />
    </div>;
  }

  if (!currentSession && !chatDraft) {
    if (loading) return <LoadingStatus />;
    return (
      <Empty className="chat-empty min-h-0">
        <EmptyHeader>
          <EmptyTitle>{t('chat:loadFailed')}</EmptyTitle>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <MessageNumbersContext.Provider value={numbers}>
    <ConversationScroller>
      <ConversationViewport
        ref={viewport}
        preserveScrollOnPrepend={false}
        aria-label={t('chat:messages')}
        onWheel={() => { userScrolling.current = true; }}
        onTouchMove={() => { userScrolling.current = true; }}
        onPointerDown={() => { userScrolling.current = true; }}
        onKeyDown={(event) => {
          if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' '].includes(event.key)) userScrolling.current = true;
        }}
        onScroll={(event) => {
          const node = event.currentTarget;
          const atEnd = node.scrollHeight - node.scrollTop - node.clientHeight < 64;
          if (userScrolling.current || atEnd) setHistoryFollowing(atEnd && !history?.has_after);
          if (historyLoading || !userScrolling.current) return;
          if (node.scrollTop < 160 && history?.has_before) {
            userScrolling.current = false;
            void page('before');
          } else if (atEnd && history?.has_after) {
            userScrolling.current = false;
            void page('after');
          }
        }}
        onClickCapture={(event) => {
          const trigger = (event.target as Element).closest('button[aria-expanded]');
          const anchor = trigger?.closest<HTMLElement>('[data-scroll-pause]');
          // Hold the visible disclosure header using the scroller's own anchor API.
          if (anchor?.dataset.messageId)
            scrollToMessage(anchor.dataset.messageId, { align: 'nearest', behavior: 'instant' });
        }}
      >
        <ConversationContent
          className={cn(!items.length && 'justify-center')}
          aria-live="polite"
        >
          {history?.has_before && <Button variant="ghost" size="sm" disabled={historyLoading} onClick={() => void page('before')}>{t('chat:loadEarlier')}</Button>}
          {!items.length ? (
            <MessageScrollerItem messageId="empty">
              <Empty className="chat-empty">
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <MessageSquare />
                  </EmptyMedia>
                  <EmptyTitle>{configuration?.persona_name}</EmptyTitle>
                  <EmptyDescription>{t('startChat')}</EmptyDescription>
                </EmptyHeader>
              </Empty>
            </MessageScrollerItem>
          ) : null}
          {items.map((item) => (
            <MessageScrollerItem key={item.id} messageId={item.id}
              scrollAnchor={item.kind === 'message' && item.message.role === 'user'}>
              {item.kind === 'message' ? (
                <MessageBubble message={item.message} messageNumber={numbers.get(item.id)} animate={animatedIds.has(item.id)} />
              ) : (
                <RunReply reply={item.reply} messageNumber={numbers.get(item.id)} showFullProcessing={showFullProcessing} />
              )}
            </MessageScrollerItem>
          ))}
          {history?.has_after && <Button variant="ghost" size="sm" disabled={historyLoading} onClick={() => void page('after')}>{t('chat:loadLater')}</Button>}
        </ConversationContent>
      </ConversationViewport>
      <UserMessageNavigation />
      {history?.has_after ? <Button variant="secondary" size="icon-sm" className="latest-message-button absolute bottom-4 left-1/2 -translate-x-1/2"
        aria-label={t('chat:scrollToEnd')} disabled={historyLoading} onClick={() => void latest()}><ArrowDown /></Button>
        : <MessageScrollerButton className="latest-message-button" aria-label={t('chat:scrollToEnd')}
            onClick={(event) => { event.preventDefault(); void latest(); }} />}
    </ConversationScroller>
    </MessageNumbersContext.Provider>
  );
}
