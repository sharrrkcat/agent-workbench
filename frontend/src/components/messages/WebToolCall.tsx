import { Globe, Search } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Badge } from '@/components/ui/badge';
import { CodeBlock, CodeBlockContent } from '@/components/ui/code-block';
import { MessageScrollerItem } from '@/components/ui/message-scroller';
import { Trace, TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceIcon, TraceLine, TraceTitle } from '@/components/ui/trace';
import type { Run } from '@/types/runs';
import { toolEntryStatus, type ToolEntry } from './turns';
import { readWebToolOutput, sourceHostname, sourceTitle } from './webSources';

export function WebToolCall({ entry, run }: { entry: ToolEntry; run: Run }) {
  const { t } = useTranslation('runs');
  const [expanded, setExpanded] = useState(true);
  const status = toolEntryStatus(entry, run);
  const search = entry.call.tool_name === 'web_search';
  const output = readWebToolOutput(entry.result);
  const value = String(entry.call.arguments[search ? 'query' : 'url'] ?? '');
  const state = status === 'waiting' ? 'pending' : status === 'rejected' ? 'error' : status;
  const title = t(`web.${search ? 'search' : 'fetch'}.${state}`, { value });
  const line = <TraceLine status={state === 'running' || state === 'pending' ? state : state === 'success' ? undefined : 'error'}>
    <TraceIcon>{search ? <Search /> : <Globe />}</TraceIcon><TraceTitle title={title}>{title}</TraceTitle>
  </TraceLine>;
  const header = <MessageScrollerItem messageId={`disclosure-web-${run.run_id}-${entry.call.tool_call_id}`} data-scroll-pause>
    {entry.result ? <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger> : line}
  </MessageScrollerItem>;
  return <Trace data-tool-call-id={entry.call.tool_call_id} data-web-tool={entry.call.tool_name}>
    <TraceCollapsible open={expanded} onOpenChange={setExpanded}>
      {header}
      {entry.result ? <TraceCollapsibleContent keepMounted>
        {entry.result.status !== 'success' ? <CodeBlock size="sm" variant="destructive">
          <CodeBlockContent wrap className="web-tool-content">{t(`web.errors.${entry.result.error_code}`, {
            defaultValue: entry.result.error_message || t('web.invalidResult'),
          })}</CodeBlockContent>
        </CodeBlock> : !output ? <span>{t('web.invalidResult')}</span> : search ? (
          output.pages.length ? <div className="flex flex-wrap gap-1.5">
            {output.pages.map((source, index) => <Badge key={`${source.url}-${index}`} variant="secondary"
              className="max-w-full pointer-coarse:min-h-11" render={<a href={source.url} target="_blank" rel="noopener noreferrer"
                title={sourceTitle(source)} aria-label={`${sourceTitle(source)}${t('web.newTab')}`} />}>
              <span className="truncate">{sourceHostname(source)}</span>
            </Badge>)}
          </div> : <span>{t('web.noResults')}</span>
        ) : <CodeBlock size="sm"><CodeBlockContent wrap className="web-tool-content">{output.content}</CodeBlockContent></CodeBlock>}
        {entry.result.truncated ? <span>{t('outputTruncated')}</span> : null}
      </TraceCollapsibleContent> : null}
    </TraceCollapsible>
  </Trace>;
}
