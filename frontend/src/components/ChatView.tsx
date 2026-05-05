import { useEffect, useRef } from 'react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { MessageBubble } from './MessageBubble';

export function ChatView() {
  const { messages, currentSession } = useWorkbenchStore();
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length]);

  if (!currentSession) {
    return <section className="chat-view empty">Create a session to begin.</section>;
  }

  return (
    <section className="chat-view">
      {messages.length === 0 ? (
        <div className="empty-state">No messages yet.</div>
      ) : (
        messages.map((message) => <MessageBubble key={message.message_id} message={message} />)
      )}
      <div ref={endRef} />
    </section>
  );
}
