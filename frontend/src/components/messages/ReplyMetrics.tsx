import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowDownToLine, ArrowUpFromLine, ChartNoAxesColumn, Gauge, Timer, type LucideIcon } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Separator } from '@/components/ui/separator';
import { ReplyActions, type ReplyDeleteAction } from './ReplyActions';
import { terminal } from '../../store/cogita/mergeState';
import { buildReplyMetrics } from './aggregateReplyMetrics';
import type { Reply } from './turns';

export function ReplyMetrics({ reply, readOnly = false, deleteAction }: { reply: Reply; readOnly?: boolean; deleteAction?: ReplyDeleteAction }) {
  const { t, i18n } = useTranslation('runs');
  const [open, setOpen] = useState(false);
  const metrics = buildReplyMetrics(reply);
  if (!metrics) return terminal(reply.run.status) || reply.run.status === 'WAITING_FOR_USER' ? <ReplyActions reply={reply} readOnly={readOnly} deleteAction={deleteAction} /> : null;
  const number = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 });
  const count = (value: number | null | undefined) => value == null ? '—' : number.format(value);
  const duration = (value: number | null | undefined) => value == null ? '—' : `${number.format(value / 1000)}s`;
  const speed = (value: number | null, estimated: boolean) => value == null ? '—' :
    `${number.format(value)} tok/s${estimated ? ` (${t('metrics.estimated')})` : ''}`;
  const item = (label: string, value: string) => (
    <div key={label}><dt>{t(`metrics.${label}`)}</dt><dd>{value}</dd></div>
  );
  const summaryItem = (label: string, value: string, Icon: LucideIcon) => (
    <Tooltip>
      <TooltipTrigger render={<div tabIndex={0} />}>
        <dt><Icon aria-hidden="true" /><span className="sr-only">{t(`metrics.${label}`)}</span></dt>
        <dd>{value}</dd>
      </TooltipTrigger>
      <TooltipContent side="bottom" collisionAvoidance={{ side: 'none', align: 'shift' }}>{t(`metrics.${label}`)}</TooltipContent>
    </Tooltip>
  );
  const summary = (
    <div className="reply-metrics">
      <dl className="reply-metrics-summary">
        {summaryItem('inputTokens', count(metrics.inputTokens), ArrowDownToLine)}
        {summaryItem('outputTokens', count(metrics.outputTokens), ArrowUpFromLine)}
        {summaryItem('firstResponse', duration(metrics.firstResponseMs), Timer)}
        {summaryItem('speed', speed(metrics.tokensPerSecond, metrics.estimated), Gauge)}
      </dl>
      <div className="reply-metrics-controls">
        {reply.run.status === 'WAITING_FOR_USER' ? <Badge variant="secondary">{t('metrics.soFar')}</Badge> : null}
        {!metrics.complete ? <Badge variant="outline">{t('metrics.incomplete')}</Badge> : null}
      </div>
    </div>
  );
  const usage = (
    <Dialog open={open} onOpenChange={setOpen}>
          <Tooltip>
            <TooltipTrigger render={
              <DialogTrigger render={<Button variant="ghost" size="icon" aria-label={t('metrics.details')} />} />
            }>
              <ChartNoAxesColumn data-icon="inline-start" />
            </TooltipTrigger>
            <TooltipContent side="bottom" collisionAvoidance={{ side: 'none', align: 'shift' }}>{t('metrics.details')}</TooltipContent>
          </Tooltip>
      <DialogContent className="reply-metrics-dialog sm:max-w-2xl" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{t('metrics.details')}</DialogTitle>
        </DialogHeader>
        <div className="reply-metrics-details">
          <dl className="reply-metrics-values">
            {item('input', count(metrics.inputTokens))}
            {item('output', count(metrics.outputTokens))}
            {item('firstResponse', duration(metrics.firstResponseMs))}
            {item('totalTime', duration(metrics.totalMs))}
            {item('speed', speed(metrics.tokensPerSecond, metrics.estimated))}
            {item('modelCalls', count(metrics.steps.length))}
          </dl>
          <div className="reply-metrics-controls">
            {reply.run.status === 'WAITING_FOR_USER' ? <Badge variant="secondary">{t('metrics.soFar')}</Badge> : null}
            {!metrics.complete ? <Badge variant="outline">{t('metrics.incomplete')}</Badge> : null}
          </div>
          <ol>
            {metrics.steps.map((step, index) => {
              const call = step.metadata?.llm;
              const usage = call?.usage;
              return (
                <li key={step.step_id}>
                  <Separator className="mb-4" />
                  <div className="reply-metrics-call">
                    <span>{t('metrics.call', { count: index + 1 })}</span>
                    <strong>{call?.model || '—'}</strong>
                    {!call?.completed ? <Badge variant="outline">{t('metrics.incomplete')}</Badge> : null}
                  </div>
                  <dl className="reply-metrics-values">
                    {item('input', count(usage?.prompt_tokens))}
                    {item('output', count(usage?.completion_tokens))}
                    {item('totalTokens', count(usage?.total_tokens))}
                    {item('cached', count(usage?.prompt_tokens_details?.cached_tokens))}
                    {item('reasoning', count(usage?.completion_tokens_details?.reasoning_tokens))}
                    {item('firstResponse', duration(call?.timing.first_response_ms))}
                    {item('callTime', duration(call?.timing.total_ms))}
                    {item('queue', duration(call?.timing.queue_ms))}
                    {item('load', duration(call?.timing.load_ms))}
                    {item('generation', duration(call?.timing.generation_ms))}
                    {item('speed', speed(call?.timing.tokens_per_second ?? null, call?.timing.tps_source === 'estimated'))}
                    {item('source', call?.timing.tps_source ? t(`metrics.${call.timing.tps_source}`) : '—')}
                  </dl>
                </li>
              );
            })}
          </ol>
        </div>
      </DialogContent>
    </Dialog>
  );
  return <div className="reply-footer" data-usage-open={open}>
    <ReplyActions reply={reply} summary={summary} usage={usage} readOnly={readOnly} deleteAction={deleteAction} />
  </div>;
}
