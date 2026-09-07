import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ArrowDown } from 'lucide-react';
import { MessageBubble } from './MessageBubble';
import { RunReply } from './messages/RunReply';
import { buildConversation } from './messages/turns';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { useTranslation } from 'react-i18next';

export function ChatView() {
  const { t } = useTranslation(['personas', 'runs']);
  const messages = useWorkbenchStore((state) => state.messages);
  const runs = useWorkbenchStore((state) => state.runs);
  const currentSession = useWorkbenchStore((state) => state.currentSession);
  const steps = useWorkbenchStore((state) => state.stepsByRunId);
  const showFullProcessing = useWorkbenchStore((state) => state.settings?.show_full_processing === true);
  const sending = useWorkbenchStore((state) => state.sending);
  const view = useRef<HTMLElement | null>(null);
  const content = useRef<HTMLDivElement | null>(null);
  const following = useRef(true);
  const [showLatest, setShowLatest] = useState(false);
  const items = useMemo(() => currentSession ? buildConversation(currentSession.session_id, messages, runs, steps) : [],
    [currentSession?.session_id, messages, runs, steps]);

  useLayoutEffect(() => {
    following.current = true;
    setShowLatest(false);
  }, [currentSession?.session_id]);

  useEffect(() => {
    const scroll = view.current;
    const body = content.current;
    if (!scroll || !body) return;
    let frame = 0;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (following.current) scroll.scrollTop = scroll.scrollHeight;
        setShowLatest(scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight > 120);
      });
    };
    const observer = new ResizeObserver(update);
    observer.observe(body);
    observer.observe(scroll);
    update();
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, [currentSession?.session_id]);

  useEffect(() => {
    if (sending && view.current) {
      following.current = true;
      view.current.scrollTop = view.current.scrollHeight;
    }
  }, [sending]);

  if (!currentSession) return <div className="chat-empty">{t('loading')}</div>;
  return (
    <div className="chat-scroll-container">
      <section ref={view} className="chat-view" onScroll={() => {
        const scroll = view.current;
        if (!scroll) return;
        following.current = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight <= 120;
        setShowLatest(!following.current);
      }} onClickCapture={(event) => {
        if ((event.target as Element).closest('button[aria-expanded]')) following.current = false;
      }}>
        <div ref={content} className="conversation-content" role="log" aria-live="polite" aria-relevant="additions">
          {!items.length ? <div className="chat-empty"><h2>{currentSession.effective.persona_name}</h2></div> : null}
          {items.map((item) => item.kind === 'message' ? <MessageBubble key={item.id} message={item.message} /> :
            <RunReply key={item.id} reply={item.reply} showFullProcessing={showFullProcessing} />)}
        </div>
      </section>
      {showLatest ? <button type="button" className="latest-message-button" title={t('runs:latestMessages')} aria-label={t('runs:latestMessages')}
        onClick={() => { following.current = true; if (view.current) view.current.scrollTop = view.current.scrollHeight; setShowLatest(false); }}><ArrowDown size={17} /></button> : null}
    </div>
  );
}
