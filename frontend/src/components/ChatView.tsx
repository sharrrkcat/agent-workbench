import { useEffect, useMemo, useRef } from 'react';
import { MessageBubble } from './MessageBubble';
import { RunPanel } from './RunPanel';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function ChatView() {
  const messages = useWorkbenchStore((state) => state.messages);
  const runs = useWorkbenchStore((state) => state.runs);
  const currentSession = useWorkbenchStore((state) => state.currentSession);
  const bottom = useRef<HTMLDivElement | null>(null);
  const activeRun = useMemo(() => [...runs].reverse().find((run) => run.session_id === currentSession?.session_id && ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(run.status)), [runs, currentSession?.session_id]);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages.length, activeRun?.status]);
  if (!currentSession) return <div className="chat-empty">Loading…</div>;
  return (
    <section className="chat-view" aria-live="polite">
      {messages.length === 0 ? <div className="chat-empty"><h2>Start a conversation</h2><p>Everything you type follows the single Chat path.</p></div> : null}
      {messages.map((message) => <MessageBubble key={message.message_id} message={message} />)}
      {activeRun ? <RunPanel run={activeRun} /> : null}
      <div ref={bottom} />
    </section>
  );
}
