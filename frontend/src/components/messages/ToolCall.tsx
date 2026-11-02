import { Terminal } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { MessageScrollerItem } from '@/components/ui/message-scroller';
import { Trace, TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceIcon, TraceLine, TraceTitle } from '@/components/ui/trace';
import type { Run } from '../../types/runs';
import { ToolResultBody } from './ToolResultBody';
import { toolArgumentsSummary } from './toolPresentation';
import { toolEntryStatus, type ToolEntry } from './turns';

export function ToolCall({ entry, run }: { entry: ToolEntry; run: Run }) {
  const { t } = useTranslation('runs');
  const [expanded, setExpanded] = useState(false);
  const status = toolEntryStatus(entry, run);
  const internal = ['context_list', 'context_search', 'context_read', 'context_checkpoint_update'].includes(entry.call.tool_name);
  const title = [t(`commandStatus.${status}`, { name: internal ? t(`retrieval.tools.${entry.call.tool_name}`) : entry.call.tool_name }), toolArgumentsSummary(entry.call.arguments)].filter(Boolean).join(' ');
  if (status === 'waiting') return null;
  if (internal) return <TraceLine status={status === 'running' ? 'running' : undefined}><TraceTitle>{title}</TraceTitle></TraceLine>;
  const line = (
    <TraceLine status={status === 'running' ? 'running' : status === 'pending' ? 'pending'
      : status === 'error' || status === 'cancelled' ? 'error' : undefined}>
      <TraceIcon><Terminal /></TraceIcon>
      <TraceTitle>{title}</TraceTitle>
    </TraceLine>
  );
  const header = (
    <MessageScrollerItem messageId={`disclosure-command-${run.run_id}-${entry.call.tool_call_id}`} data-scroll-pause>
      {entry.result ? <TraceCollapsibleTrigger>{line}</TraceCollapsibleTrigger> : line}
    </MessageScrollerItem>
  );
  return (
    <Trace data-tool-call-id={entry.call.tool_call_id}>
      {entry.result ? <TraceCollapsible open={expanded} onOpenChange={setExpanded}>
        {header}
        <TraceCollapsibleContent><ToolResultBody part={entry.result} /></TraceCollapsibleContent>
      </TraceCollapsible> : header}
    </Trace>
  );
}

