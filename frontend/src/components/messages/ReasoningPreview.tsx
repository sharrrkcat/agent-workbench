import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Brain } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { MessageScrollerItem } from '@/components/ui/message-scroller';
import type { ReasoningPart } from '../../types/messages';
import { MessageParts } from './MessageParts';
import { reasoningText } from './reasoningText';

export function ReasoningPreview({ id, part, streaming }: { id: string; part: ReasoningPart; streaming: boolean }) {
  const { t } = useTranslation('runs');
  const [expanded, setExpanded] = useState(false);
  const [overflowing, setOverflowing] = useState(false);
  const preview = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLSpanElement>(null);
  const text = useMemo(() => reasoningText(part.text), [part.text]);

  useLayoutEffect(() => {
    if (!streaming) setExpanded(false);
  }, [streaming]);

  useLayoutEffect(() => {
    const node = content.current;
    const container = preview.current;
    if (!node || !container) return;
    const measure = () => setOverflowing(node.getBoundingClientRect().width > container.getBoundingClientRect().width);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    observer.observe(container);
    return () => observer.disconnect();
  }, [expanded, text]);

  const body = <div className="reasoning-content"><MessageParts parts={[part]} /></div>;
  return (
    <Collapsible open={expanded} onOpenChange={setExpanded} className="processing-reasoning">
      <MessageScrollerItem messageId={`disclosure-${id}`} data-scroll-pause>
        <CollapsibleTrigger
          disabled={!overflowing && !expanded}
          aria-label={t(expanded ? 'collapseReasoning' : 'expandReasoning')}
          render={<Button variant="ghost" size="icon-sm" className="reasoning-toggle" />}
        >
          <Brain data-icon="inline-start" />
        </CollapsibleTrigger>
      </MessageScrollerItem>
      {!expanded ? (
        <div ref={preview} className="reasoning-preview" data-streaming={streaming} data-overflowing={overflowing}>
          {overflowing && streaming ? <span className="reasoning-ellipsis" aria-hidden="true">…</span> : null}
          <div className="reasoning-window">
            <span ref={content} className="reasoning-preview-text">{text}</span>
          </div>
          {overflowing && !streaming ? <span className="reasoning-ellipsis" aria-hidden="true">…</span> : null}
        </div>
      ) : null}
      <CollapsibleContent id={id}>{expanded ? body : null}</CollapsibleContent>
    </Collapsible>
  );
}
