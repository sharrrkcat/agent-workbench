import { Check, ChevronRight, Clock3, LoaderCircle, Terminal, X } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { Run } from '../../types/runs';
import { MessageContextAction } from './MessageActions';
import { ToolResultBody } from './ToolResultBody';
import { toolEntryStatus, type ToolEntry } from './turns';

export function ToolGroup({ calls, run }: { calls: ToolEntry[]; run: Run }) {
  const { t } = useTranslation('runs');
  const [expanded, setExpanded] = useState(false);
  const statuses = calls.map((entry) => toolEntryStatus(entry, run));
  const active = statuses.some((status) => ['pending', 'running', 'waiting'].includes(status));
  const errors = statuses.filter((status) => ['error', 'rejected', 'cancelled'].includes(status)).length;
  const id = `commands-${run.run_id}-${calls[0].call.tool_call_id}`;
  return <div className="tool-group">
    <button type="button" className="process-disclosure tool-group-toggle" aria-expanded={expanded} aria-controls={id}
      onClick={() => setExpanded((value) => !value)}>
      <ChevronRight size={14} className={expanded ? 'expanded' : ''} /><Terminal size={15} />
      <span>{t(active ? 'commandsRunning' : 'commands', { count: calls.length })}</span>
      {errors ? <span className="tool-group-errors">{t('commandIssues', { count: errors })}</span> : null}
    </button>
    {expanded ? <div id={id} className="tool-group-list">{calls.map((entry) => <ToolCommand key={entry.call.tool_call_id} entry={entry} run={run} />)}</div> : null}
  </div>;
}

function ToolCommand({ entry, run }: { entry: ToolEntry; run: Run }) {
  const { t } = useTranslation('runs');
  const [expanded, setExpanded] = useState(false);
  const status = toolEntryStatus(entry, run);
  const Icon = status === 'success' ? Check : status === 'running' ? LoaderCircle : ['pending', 'waiting'].includes(status) ? Clock3 : X;
  const id = `command-${run.run_id}-${entry.call.tool_call_id}`;
  return <div className={`tool-command command-${status}`}>
    <button type="button" className="process-disclosure tool-command-toggle" aria-expanded={expanded} aria-controls={id}
      onClick={() => setExpanded((value) => !value)}>
      <ChevronRight size={13} className={expanded ? 'expanded' : ''} />
      <Icon size={14} className={status === 'running' ? 'process-spinner' : ''} />
      <span>{t(`commandStatus.${status}`, { name: entry.call.tool_name })}</span>
    </button>
    {expanded ? <div className="tool-command-details" id={id}>
      <div className="tool-detail-label"><span>{t('arguments')}</span><MessageContextAction message={entry.message} /></div>
      <pre className="part-json">{JSON.stringify(entry.call.arguments, null, 2)}</pre>
      {entry.result ? <>
        <div className="tool-detail-label"><span>{t('result')}</span>{entry.resultMessage ? <MessageContextAction message={entry.resultMessage} /> : null}</div>
        <ToolResultBody part={entry.result} />
      </> : null}
    </div> : null}
  </div>;
}
