import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Marker, MarkerContent } from '@/components/ui/marker';
import { MessageScrollerItem } from '@/components/ui/message-scroller';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { ChevronRight, LoaderCircle } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { terminal } from '../../store/cogita/mergeState';
import type { Run } from '../../types/runs';
import { MessageFrame } from './MessageFrame';
import { MessageParts } from './MessageParts';
import { RunApproval } from './RunApproval';
import { ReplyMetrics } from './ReplyMetrics';
import { ToolGroup } from './ToolGroup';
import { ReasoningPreview } from './ReasoningPreview';
import type { Reply } from './turns';
import { imageErrorKey } from './messageContent';
import { usePersonaIdentity } from '../../hooks/usePersonaIdentity';

export function RunReply({ reply, messageNumber, showFullProcessing, readOnly = false }: { reply: Reply; messageNumber?: number; showFullProcessing: boolean; readOnly?: boolean }) {
  const { t } = useTranslation(['runs', 'personas']);
  const { run, process, answer, answerParts } = reply;
  const ended = terminal(run.status);
  const [expanded, setExpanded] = useState(() => !ended && showFullProcessing);
  useEffect(() => {
    setExpanded(!ended && showFullProcessing);
  }, [ended, showFullProcessing]);
  const seconds = useRunSeconds(run);
  const identity = usePersonaIdentity()(run.persona_id);
  const processId = `processing-${run.run_id}`;
  const error = run.error_message || run.error || '';
  const contextErrors: Record<string, string> = { CONTEXT_WINDOW_REQUIRED: 'contextErrors.required',
    CONTEXT_WINDOW_EXCEEDED: 'contextErrors.exceeded', CONTEXT_COUNT_FAILED: 'contextErrors.countFailed' };
  const errorKey = contextErrors[run.error_code ?? ''] ?? imageErrorKey(run.error_code, error);
  const status = (
    {
      PENDING: 'queued',
      WAITING_FOR_USER: 'waiting',
      CANCELLING: 'cancelling',
      FAILED: 'failed',
      CANCELLED: 'cancelled',
      INTERRUPTED: 'interrupted',
    } as Partial<Record<Run['status'], string>>
  )[run.status];
  return (
    <MessageFrame
      role="assistant"
      name={identity.name}
      avatarId={identity.avatar_attachment_id}
      createdAt={run.created_at}
      runId={run.run_id}
      messageNumber={messageNumber}
    >
      <Collapsible open={expanded} onOpenChange={setExpanded}>
        <MessageScrollerItem messageId={'disclosure-' + processId} data-scroll-pause>
          <div className={`reply-processing-header status-${run.status.toLowerCase()}`}>
            <CollapsibleTrigger
              render={
                <Button
                  type="button"
                  disabled={ended && process.length === 0}
                  variant="ghost"
                  className="process-disclosure processing-toggle"
                />
              }
            >
              {!ended ? <LoaderCircle size={14} className="animate-spin" /> : null}
              <span>{t(ended ? 'elapsed' : 'processing', { seconds })}</span>
              {process.length || !ended ? (
                <ChevronRight data-icon="inline-end" className={expanded ? 'disclosure-arrow expanded' : 'disclosure-arrow'} />
              ) : null}
            </CollapsibleTrigger>
            {status ? (
              <span className="reply-run-status" role="status">
                {t(status)}
              </span>
            ) : null}
          </div>
        </MessageScrollerItem>
        <CollapsibleContent id={processId} className="processing-timeline">
          {process.map((item) =>
            item.kind === 'tools' ? (
              <ToolGroup key={item.id} calls={item.calls} run={run} />
            ) : item.part.type === 'reasoning' ? (
              <ReasoningPreview
                key={`${item.message.message_id}-${item.id}`}
                id={`reasoning-${item.message.message_id}-${item.id}`}
                part={item.part}
                streaming={!ended && item.message.metadata?.streaming === true && item.message.parts[item.message.parts.length - 1]?.id === item.id}
              />
            ) : (
              <div
                className="processing-content"
                key={`${item.message.message_id}-${item.id}`}
              >
                <div className="processing-content-body">
                  <MessageParts parts={[item.part]} />
                </div>
              </div>
            ),
          )}
          {!process.length && !ended ? <span className="run-muted">{t('preparing')}</span> : null}
        </CollapsibleContent>
      </Collapsible>
      {!readOnly && <RunApproval run={run} steps={reply.steps} messages={reply.messages} />}
      {error ? (
        <Alert className="reply-error" variant="destructive">
          <AlertDescription>
            {run.error_code ? `${run.error_code}: ` : ''}
            {errorKey ? t(errorKey) : error}
          </AlertDescription>
        </Alert>
      ) : null}
      {answer?.metadata?.incomplete ? (
        <Marker className="reply-incomplete">
          <MarkerContent>{t('incompleteAnswer')}</MarkerContent>
        </Marker>
      ) : null}
      {answerParts.length ? (
        <div className="message reply-answer" data-message-id={answer?.message_id}>
          <MessageParts parts={answerParts} />
          {answer?.metadata?.streaming ? <span className="streaming-cursor" aria-hidden="true" /> : null}
        </div>
      ) : null}
      {ended || run.status === 'WAITING_FOR_USER' ? <ReplyMetrics reply={reply} readOnly={readOnly} /> : null}
    </MessageFrame>
  );
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
