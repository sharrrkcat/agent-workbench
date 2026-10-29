import { ArrowUpRight, Globe } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { MessageScrollerItem } from '@/components/ui/message-scroller';
import { Trace, TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceIcon, TraceLine, TraceTitle } from '@/components/ui/trace';
import type { WebSource } from '@/types/tools';
import { sourceTitle } from './webSources';

export function WebSources({ sources, runId }: { sources: WebSource[]; runId: string }) {
  const { t } = useTranslation('runs');
  if (!sources.length) return null;
  return <Trace data-web-sources>
    <TraceCollapsible>
      <MessageScrollerItem messageId={`disclosure-sources-${runId}`} data-scroll-pause>
        <TraceCollapsibleTrigger>
          <TraceLine><TraceIcon><Globe /></TraceIcon><TraceTitle>{t('web.sources', { count: sources.length })}</TraceTitle></TraceLine>
        </TraceCollapsibleTrigger>
      </MessageScrollerItem>
      <TraceCollapsibleContent>
        <Trace>{sources.map((source) => <a key={source.url} href={source.url} target="_blank" rel="noopener noreferrer"
          title={sourceTitle(source)} className="web-source-link">
          <TraceLine>
            <TraceIcon><Globe /></TraceIcon>
            <TraceTitle>{sourceTitle(source)}<span className="sr-only">{t('web.newTab')}</span></TraceTitle>
            <TraceIcon><ArrowUpRight /></TraceIcon>
          </TraceLine>
        </a>)}</Trace>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  </Trace>;
}
