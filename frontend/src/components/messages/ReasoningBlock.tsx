import { CircleCheck, LoaderCircle } from 'lucide-react';
import { useEffect, useEffectEvent, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { MessageScrollerItem } from '@/components/ui/message-scroller';
import { Trace, TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceIcon, TraceLine, TraceTitle } from '@/components/ui/trace';
import type { ReasoningPart } from '../../types/messages';
import { MessageParts } from './MessageParts';

export function ReasoningBlock({ part, streaming }: { part: ReasoningPart; streaming: boolean }) {
  const { t } = useTranslation('runs');
  const [expanded, setExpanded] = useState(false);
  const wasStreaming = useRef(streaming);
  const scheduleClose = useEffectEvent(() => expanded ? setTimeout(() => setExpanded(false), 1000) : undefined);
  useEffect(() => {
    const finished = wasStreaming.current && !streaming;
    wasStreaming.current = streaming;
    if (!finished) return;
    const timer = scheduleClose();
    return () => clearTimeout(timer);
  }, [streaming]);
  const title = streaming ? t('thinking') : part.duration_ms == null ? t('thought')
    : t('thoughtDuration', { seconds: Math.ceil(part.duration_ms / 1000) });
  return (
    <Trace data-reasoning-id={part.id}>
      <TraceCollapsible open={expanded} onOpenChange={setExpanded}>
        <MessageScrollerItem messageId={`disclosure-${part.id}`} data-scroll-pause>
          <TraceCollapsibleTrigger>
            <TraceLine status={streaming ? 'running' : undefined}>
              <TraceIcon>{streaming ? <LoaderCircle className="animate-spin motion-reduce:animate-none" /> : <CircleCheck />}</TraceIcon>
              <TraceTitle>{title}</TraceTitle>
            </TraceLine>
          </TraceCollapsibleTrigger>
        </MessageScrollerItem>
        <TraceCollapsibleContent id={`reasoning-${part.id}`}><MessageParts parts={[part]} compact /></TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  );
}
