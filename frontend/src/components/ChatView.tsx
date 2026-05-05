import { useEffect, useRef } from 'react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { MessageBubble } from './MessageBubble';

export function ChatView() {
  const { messages, currentSession, createSession, loading } = useWorkbenchStore();
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length]);

  if (!currentSession) {
    return (
      <section className="chat-view empty">
        <div className="empty-state">
          <p>No session yet.</p>
          <button onClick={() => void createSession()} disabled={loading}>
            Create session
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="chat-view">
      {messages.length === 0 ? (
        <div className="empty-state">
          <p>Try one of these:</p>
          <code>hello</code>
          <code>@translate 你好</code>
          <code>/base64 hello</code>
        </div>
      ) : (
        messages.map((message) => <MessageBubble key={message.message_id} message={message} />)
      )}
      <div ref={endRef} />
    </section>
  );
}
