import { Brain, ChevronRight, LoaderCircle } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { terminal } from '../../store/workbench/mergeState';
import type { Run } from '../../types/runs';
import { MessageFrame } from './MessageFrame';
import { MessageParts } from './MessageParts';
import { MessageContextAction } from './MessageActions';
import { RunApproval, RunCancelButton } from './RunApproval';
import { ReplyActions } from './ReplyActions';
import { ToolGroup } from './ToolGroup';
import type { Reply } from './turns';

export function RunReply({ reply, showFullProcessing }: { reply: Reply; showFullProcessing: boolean }) {
  const { t } = useTranslation(['runs', 'personas']);
  const { run, process, answer, answerParts } = reply;
  const ended = terminal(run.status);
  const [expanded, setExpanded] = useState(() => !ended && showFullProcessing);
  useEffect(() => { setExpanded(!ended && showFullProcessing); }, [ended, showFullProcessing]);
  const seconds = useRunSeconds(run);
  const first = reply.messages.find((message) => message.role === 'assistant');
  const configuration = run.metadata?.configuration as { persona_name?: string; avatar_attachment_id?: string | null } | undefined;
  const name = first?.speaker_name || configuration?.persona_name || t('personas:assistant');
  const avatar = first?.metadata?.speaker_avatar_attachment_id ?? configuration?.avatar_attachment_id;
  const processId = `processing-${run.run_id}`;
  const status = ({ PENDING: 'queued', WAITING_FOR_USER: 'waiting', CANCELLING: 'cancelling', FAILED: 'failed', CANCELLED: 'cancelled', INTERRUPTED: 'interrupted' } as Partial<Record<Run['status'], string>>)[run.status];
  return <MessageFrame role="assistant" name={name} avatarId={typeof avatar === 'string' ? avatar : null}
    createdAt={run.created_at} runId={run.run_id}>
    <div className={`reply-processing-header status-${run.status.toLowerCase()}`}>
      <button type="button" className="process-disclosure processing-toggle" aria-expanded={expanded} aria-controls={processId}
        disabled={ended && process.length === 0} onClick={() => setExpanded((value) => !value)}>
        {process.length || !ended ? <ChevronRight size={14} className={expanded ? 'expanded' : ''} /> : null}
        {!ended ? <LoaderCircle size={14} className="process-spinner" /> : null}
        <span>{t(ended ? 'elapsed' : 'processing', { seconds })}</span>
      </button>
      {status ? <span className="reply-run-status" role="status">{t(status)}</span> : null}
      {!ended ? <RunCancelButton run={run} /> : null}
    </div>
    {expanded ? <div id={processId} className="processing-timeline">
      {process.map((item) => item.kind === 'tools' ? <ToolGroup key={item.id} calls={item.calls} run={run} /> :
        <div className={`processing-content ${item.part.type === 'reasoning' ? 'processing-reasoning' : ''}`} key={`${item.message.message_id}-${item.id}`}>
          {item.part.type === 'reasoning' ? <Brain size={14} aria-label={t('reasoning')} /> : null}
          <div className="processing-content-body"><MessageParts parts={[item.part]} />{item.part.type !== 'reasoning' ? <MessageContextAction message={item.message} /> : null}</div>
        </div>)}
      {!process.length && !ended ? <span className="run-muted">{t('preparing')}</span> : null}
    </div> : null}
    <RunApproval run={run} steps={reply.steps} messages={reply.messages} />
    {run.error_message || run.error ? <p className="reply-error" role="alert">{run.error_code ? `${run.error_code}: ` : ''}{run.error_message || run.error}</p> : null}
    {answer?.metadata?.incomplete ? <p className="reply-incomplete">{t('incompleteAnswer')}</p> : null}
    {answerParts.length ? <div className="message reply-answer" data-message-id={answer?.message_id}>
      <MessageParts parts={answerParts} />
      {answer?.metadata?.streaming ? <span className="streaming-cursor" aria-hidden="true" /> : null}
    </div> : null}
    {ended ? <ReplyActions reply={reply} /> : null}
  </MessageFrame>;
}

function useRunSeconds(run: Run): number {
  const [now, setNow] = useState(Date.now);
  const ended = terminal(run.status);
  useEffect(() => {
    if (ended) return;
    setNow(Date.now());
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [run.run_id, ended]);
  const start = Date.parse(run.started_at || run.created_at);
  const end = ended ? Date.parse(run.finished_at || run.updated_at) : now;
  return Number.isFinite(start) && Number.isFinite(end) ? Math.max(0, Math.floor((end - start) / 1000)) : 0;
}
