import { useTranslation } from 'react-i18next';
import { Marker, MarkerContent } from '@/components/ui/marker';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useCogitaStore } from '../../store/useCogitaStore';
import { terminal } from '../../store/cogita/mergeState';
import { ReplyContext } from './ReplyContext';
import { ReplyMetrics } from './ReplyMetrics';
import type { Reply } from './turns';

export function CompactionEvent({ reply }: { reply: Reply }) {
  const { t, i18n } = useTranslation('runs');
  const cancel = useCogitaStore((state) => state.cancelRun);
  const { run } = reply;
  const result = run.metadata?.compaction;
  const ended = terminal(run.status);
  const key = run.status === 'DONE' ? result?.status === 'not_needed' ? 'notNeeded' : 'completed'
    : run.status === 'FAILED' ? 'failed' : run.status === 'CANCELLED' ? 'cancelled'
    : run.status === 'INTERRUPTED' ? 'interrupted' : run.status === 'CANCELLING' ? 'cancelling' : 'running';
  const label = <span role="status">{t(result?.operation === 'reset' && key === 'completed' ? 'retrieval.reset' : `compaction.${key}`)}</span>;
  return <Marker variant="separator" className="my-4" data-compaction-run={run.run_id}>
    <MarkerContent className="inline-flex flex-wrap items-center justify-center gap-2">
      {run.error_message ? <Tooltip><TooltipTrigger render={<span tabIndex={0} />}>{label}</TooltipTrigger>
        <TooltipContent>{run.error_message}</TooltipContent></Tooltip> : label}
      {(result?.status === 'compacted' || result?.status === 'reset') && result.input_tokens_before != null && result.input_tokens_after != null ?
        <span>{result.input_tokens_before.toLocaleString(i18n.language)} → {result.input_tokens_after.toLocaleString(i18n.language)} tokens</span> : null}
      {!ended ? <Button size="xs" variant="outline" disabled={run.status === 'CANCELLING'}
        onClick={() => void cancel(run.run_id)}>{t('cancel')}</Button> : <><ReplyContext reply={reply} /><ReplyMetrics reply={reply} /></>}
    </MarkerContent>
  </Marker>;
}
