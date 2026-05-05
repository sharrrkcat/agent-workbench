import { useEffect, useRef } from 'react';
import { MessageSquarePlus, Sparkles } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { MessageBubble } from './MessageBubble';

export function ChatView() {
  const { messages, currentSession, createSession, loading, sendMessage, sending } = useWorkbenchStore();
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length]);

  if (!currentSession) {
    return (
      <section className="chat-view empty">
        <div className="empty-state">
          <div className="empty-icon">
            <MessageSquarePlus size={22} />
          </div>
          <h1>Start a local AI session</h1>
          <p>Create a session to talk to the default agent or call an agent/command directly.</p>
          <button className="empty-primary" onClick={() => void createSession()} disabled={loading}>
            New Chat
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="chat-view">
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
        messages.map((message) => <MessageBubble key={message.message_id} message={message} />)
      )}
      <div ref={endRef} />
    </section>
  );
}
