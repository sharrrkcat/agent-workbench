import { Fragment, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';
import type { WebSource } from '@/types/tools';
import { citationMatches, sourceHostname, sourceTitle, type WebSourceMap } from './webSources';

export function WebCitation({ source }: { source: WebSource }) {
  const { t } = useTranslation('runs');
  const [open, setOpen] = useState(false);
  const pressed = useRef(false);
  return <HoverCard open={open} onOpenChange={(next, event) => {
    if (!next && pressed.current && (event.reason === 'trigger-hover' || event.reason === 'trigger-focus')) return;
    if (!next) pressed.current = false;
    setOpen(next);
  }}>
    <HoverCardTrigger delay={10} closeDelay={100} render={<Button variant="secondary" size="xs"
      className="web-citation max-w-full align-baseline" data-web-citation={source.source_id}
      aria-label={t('web.citation', { title: sourceTitle(source) })}
      onFocus={() => setOpen(true)} onClick={() => { pressed.current = true; setOpen(true); }} />}>
      <span className="truncate">{sourceHostname(source)}</span>
    </HoverCardTrigger>
    <HoverCardContent className="flex w-64 max-w-[calc(100vw-2rem)] flex-col gap-1 wrap-anywhere" align="start">
      <strong>{sourceTitle(source)}</strong>
      <a href={source.url} target="_blank" rel="noopener noreferrer" className="web-source-link">
        {sourceHostname(source)}<span className="sr-only">{t('web.newTab')}</span>
      </a>
    </HoverCardContent>
  </HoverCard>;
}

export function PlainWebCitations({ text, sources }: { text: string; sources: WebSourceMap }) {
  let start = 0;
  const nodes = citationMatches(text, sources).map((match) => {
    const prefix = text.slice(start, match.start);
    start = match.end;
    return <Fragment key={match.start}>{prefix}<WebCitation source={match.source} /></Fragment>;
  });
  return <>{nodes}{text.slice(start)}</>;
}
