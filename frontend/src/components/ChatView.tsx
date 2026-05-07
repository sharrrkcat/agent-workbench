import { useLayoutEffect, useRef } from 'react';
import { MessageSquarePlus, Sparkles } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { Message } from '../types';
import { MessageBubble, type FilePreview } from './MessageBubble';
import type { ImagePreview } from '../utils/images';

export function ChatView({ onPreviewImage, onPreviewFile }: { onPreviewImage: (image: ImagePreview) => void; onPreviewFile: (file: FilePreview) => void }) {
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
          <h1>Start a local AI session</h1>
          <p>Create a session to talk to the default agent or call an agent/command directly.</p>
          <button className="empty-primary" onClick={() => void createSession()} disabled={loading || creatingSession}>
            {creatingSession ? 'Creating...' : 'New Chat'}
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
          <p>Chat with the default agent, invoke a named agent, or run a slash command.</p>
          <div className="prompt-chips" aria-label="Example prompts">
            {['hello', '@translate 你好', '/base64 hello'].map((prompt) => (
              <button key={prompt} type="button" onClick={() => void sendMessage(prompt)} disabled={sending}>
                {prompt}
              </button>
            ))}
          </div>
        </div>
      ) : (
        messages.map((message) => <MessageBubble key={message.message_id} message={message} onPreviewImage={onPreviewImage} onPreviewFile={onPreviewFile} />)
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
