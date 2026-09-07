import { useEffect, useMemo, useRef } from 'react';
import { MessageBubble } from './MessageBubble';
import { RunPanel } from './RunPanel';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { useTranslation } from 'react-i18next';

export function ChatView() {
  const { t } = useTranslation('personas');
  const messages = useWorkbenchStore((state) => state.messages);
  const runs = useWorkbenchStore((state) => state.runs);
  const currentSession = useWorkbenchStore((state) => state.currentSession);
  const bottom = useRef<HTMLDivElement | null>(null);
  const activeRun = useMemo(() => [...runs].reverse().find((run) => run.session_id === currentSession?.session_id && ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(run.status)), [runs, currentSession?.session_id]);
  const visibleRun = activeRun || [...runs].reverse().find((run) => run.session_id === currentSession?.session_id);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages.length, activeRun?.status]);
  if (!currentSession) return <div className="chat-empty">{t('loading')}</div>;
  return (
    <section className="chat-view" aria-live="polite">
      {messages.length === 0 ? <div className="chat-empty"><h2>{currentSession.effective.persona_name}</h2></div> : null}
      {messages.map((message) => <MessageBubble key={message.message_id} message={message} />)}
      {visibleRun ? <RunPanel run={visibleRun} /> : null}
      <div ref={bottom} />
    </section>
  );
}
