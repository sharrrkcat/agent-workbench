import { useLayoutEffect, useRef } from 'react';
import { MessageSquarePlus, Sparkles } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { Message, SystemNotification, TimelineItem } from '../types';
import { MessageBubble, type FilePreview } from './MessageBubble';
import type { ImagePreview } from '../utils/images';

export function ChatView({ onPreviewImage, onPreviewFile }: { onPreviewImage: (image: ImagePreview) => void; onPreviewFile: (file: FilePreview) => void }) {
  const { t } = useTranslation();
  const { messages, currentSession, createSession, loading, creatingSession, sendMessage, sending } = useWorkbenchStore();
  const scrollRef = useRef<HTMLElement | null>(null);
  const autoScrollRef = useRef(true);
  const previousSessionIdRef = useRef<string | undefined>(currentSession?.session_id);

  useLayoutEffect(() => {
    const sessionId = currentSession?.session_id;
    if (previousSessionIdRef.current !== sessionId) {
      previousSessionIdRef.current = sessionId;
      autoScrollRef.current = true;
    }

    const container = scrollRef.current;
    if (!container) return;
    const lastMessage = messages[messages.length - 1];
    const shouldResumeForUserMessage = lastMessage?.role === 'user' && lastMessage.client_status === 'pending';
    if (shouldResumeForUserMessage) {
      autoScrollRef.current = true;
    }
    if (!autoScrollRef.current && !shouldResumeForUserMessage) return;
    window.requestAnimationFrame(() => {
      if (previousSessionIdRef.current !== sessionId) return;
      scrollToBottom(container);
    });
  }, [currentSession?.session_id, messagesSignature(messages)]);

  function handleScroll() {
    const container = scrollRef.current;
    if (!container) return;
    autoScrollRef.current = isNearBottom(container);
  }

  if (!currentSession) {
    return (
      <section className="chat-view empty">
        <div className="empty-state">
          <div className="empty-icon">
            <MessageSquarePlus size={22} />
          </div>
          <h1>{t('chat:startSessionTitle')}</h1>
          <p>{t('chat:startSessionDescription')}</p>
          <button className="empty-primary" onClick={() => void createSession()} disabled={loading || creatingSession}>
            {creatingSession ? t('common:creating') : t('chat:newChat')}
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="chat-view" ref={scrollRef} onScroll={handleScroll}>
      {messages.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">
            <Sparkles size={22} />
          </div>
          <h1>Agent Workbench</h1>
          <p>{t('chat:emptySessionDescription')}</p>
          <div className="prompt-chips" aria-label={t('chat:examplePrompts')}>
            {['hello', '@translate 你好', '/base64 hello'].map((prompt) => (
              <button key={prompt} type="button" onClick={() => void sendMessage(prompt)} disabled={sending}>
                {prompt}
              </button>
            ))}
          </div>
        </div>
      ) : (
        toTimelineItems(messages).map((item) =>
          item.kind === 'message' ? (
            <MessageBubble key={item.message.message_id} message={item.message} onPreviewImage={onPreviewImage} onPreviewFile={onPreviewFile} />
          ) : (
            <MessageBubble key={item.notification.id} message={notificationToMessage(item.notification)} onPreviewImage={onPreviewImage} onPreviewFile={onPreviewFile} />
          ),
        )
      )}
    </section>
  );
}

function isNearBottom(container: HTMLElement): boolean {
  return container.scrollHeight - container.scrollTop - container.clientHeight < 160;
}

function scrollToBottom(container: HTMLElement) {
  container.scrollTop = container.scrollHeight;
}

function messagesSignature(messages: Message[]): string {
  return messages
    .map((message) => {
      const text = typeof message.content === 'string' ? message.content : JSON.stringify(message.content ?? '');
      const reasoning =
        typeof message.metadata?.reasoning_content === 'string'
          ? message.metadata.reasoning_content
          : typeof (message.metadata?.reasoning as Record<string, unknown> | undefined)?.content === 'string'
            ? String((message.metadata?.reasoning as Record<string, unknown>).content)
            : '';
      return `${message.message_id}:${message.client_status || ''}:${text.length}:${reasoning.length}`;
    })
    .join('|');
}

function toTimelineItems(messages: Message[]): TimelineItem[] {
  return messages.map((message) => {
    if (isSystemNotificationMessage(message)) {
      return { kind: 'notification', notification: messageToNotification(message) };
    }
    return { kind: 'message', message };
  });
}

function isSystemNotificationMessage(message: Message): boolean {
  return message.role === 'system' && (message.output_type === 'error' || message.metadata?.notification === true);
}

function messageToNotification(message: Message): SystemNotification {
  const content = isRecord(message.content) ? message.content : {};
  return {
    id: message.message_id,
    session_id: message.session_id,
    run_id: message.run_id,
    severity: typeof message.metadata?.severity === 'string' ? message.metadata.severity : 'error',
    code: typeof message.client_error?.code === 'string' ? message.client_error.code : typeof content.code === 'string' ? content.code : null,
    message: typeof message.client_error?.message === 'string' ? message.client_error.message : typeof content.message === 'string' ? content.message : String(message.content || ''),
    created_at: message.created_at,
    metadata: message.metadata,
  };
}

function notificationToMessage(notification: SystemNotification): Message {
  return {
    message_id: notification.id,
    session_id: notification.session_id,
    role: 'system',
    content: { code: notification.code, message: notification.message },
    agent_id: null,
    command_name: null,
    action_id: null,
    run_id: notification.run_id || null,
    output_type: 'error',
    parent_message_id: typeof notification.metadata?.parent_message_id === 'string' ? notification.metadata.parent_message_id : null,
    available_actions: [],
    metadata: { ...(notification.metadata || {}), notification: true, severity: notification.severity },
    created_at: notification.created_at,
    client_status: 'failed',
    client_error: { code: notification.code || 'NOTIFICATION', message: notification.message },
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}
