import { useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { MessageSquare } from 'lucide-react';
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
  useMessageScroller,
} from '@/components/ui/message-scroller';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { LoadingStatus } from '@/components/ui/loading-status';
import { cn } from '@/lib/utils';
import { MessageBubble } from './MessageBubble';
import { RunReply } from './messages/RunReply';
import { buildConversation } from './messages/turns';
import { useCogitaStore } from '../store/useCogitaStore';
import { ResourceLoading } from './settings/resources/ResourceUI';
import { useChatConfiguration } from '../hooks/useChatConfiguration';

export function ChatView() {
  return (
    <MessageScrollerProvider autoScroll scrollEdgeThreshold={32}>
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
  const items = useMemo(
    () => (currentSession ? buildConversation(currentSession.session_id, messages, runs, steps) : []),
    [currentSession?.session_id, messages, runs, steps],
  );

  useEffect(() => {
    if (sending) scrollToEnd({ behavior: 'instant' });
  }, [sending, scrollToEnd]);

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
    <MessageScroller className="chat-scroll-container h-auto flex-1">
      <MessageScrollerViewport
        className="chat-view"
        aria-label={t('chat:messages')}
        onClickCapture={(event) => {
          const trigger = (event.target as Element).closest('button[aria-expanded]');
          const anchor = trigger?.closest<HTMLElement>('[data-scroll-pause]');
          // Hold the visible disclosure header using the scroller's own anchor API.
          if (anchor?.dataset.messageId)
            scrollToMessage(anchor.dataset.messageId, { align: 'nearest', behavior: 'instant' });
        }}
      >
        <MessageScrollerContent
          className={cn('conversation-content', !items.length && 'justify-center')}
          aria-live="polite"
        >
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
            <MessageScrollerItem key={item.id} messageId={item.id}>
              {item.kind === 'message' ? (
                <MessageBubble message={item.message} />
              ) : (
                <RunReply reply={item.reply} showFullProcessing={showFullProcessing} />
              )}
            </MessageScrollerItem>
          ))}
        </MessageScrollerContent>
      </MessageScrollerViewport>
      <MessageScrollerButton className="latest-message-button" aria-label={t('chat:scrollToEnd')} />
    </MessageScroller>
  );
}
