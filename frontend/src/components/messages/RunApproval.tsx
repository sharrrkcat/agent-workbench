import { Button } from '@/components/ui/button';
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Check, ShieldAlert, Square, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { Message } from '../../types/messages';
import type { Run, RunStep } from '../../types/runs';

export function RunApproval({ run, steps, messages }: { run: Run; steps: RunStep[]; messages: Message[] }) {
  const { t } = useTranslation('runs');
  const resolve = useWorkbenchStore((state) => state.resolveApproval);
  const resolving = useWorkbenchStore((state) => state.resolvingApprovals.includes(run.run_id));
  const approval = steps.find((step) => step.kind === 'approval' && step.status === 'running');
  if (run.status !== 'WAITING_FOR_USER' || !approval) return null;
  const call = messages
    .filter((message) => message.run_id === run.run_id)
    .flatMap((message) => message.parts)
    .find((part) => part.type === 'tool_call' && part.tool_call_id === approval.metadata?.tool_call_id);
  const ready = call?.type === 'tool_call';
  return (
    <Alert className="approval-details" role="region" aria-label={t('waiting')}>
      <ShieldAlert />
      <AlertTitle className="approval-heading">{ready ? call.tool_name : t('waiting')}</AlertTitle>
      <AlertDescription>
        <p>{t(`approvalRisk.${String(approval.metadata?.risk || 'safe')}`)}</p>
        {ready ? (
          <pre className="part-json">{JSON.stringify(call.arguments, null, 2)}</pre>
        ) : (
          <p>{t('preparing')}</p>
        )}
        {typeof approval.metadata?.service_url === 'string' ? (
          <p>
            {t('service')}: {approval.metadata.service_url}
          </p>
        ) : null}
        <div className="approval-actions">
          <Button
            type="button"
            disabled={resolving || !ready}
            onClick={() => void resolve(run.run_id, 'reject')}
            variant="outline"
          >
            <X size={14} />
            {t('reject')}
          </Button>
          <Button
            type="button"
            disabled={resolving || !ready}
            onClick={() => void resolve(run.run_id, 'approve')}
            variant="default"
          >
            <Check data-icon="inline-start" />
            {t(resolving ? 'resuming' : 'approve')}
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  );
}

export function RunCancelButton({ run }: { run: Run }) {
  const { t } = useTranslation('runs');
  const cancel = useWorkbenchStore((state) => state.cancelRun);
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            type="button"
            disabled={run.status === 'CANCELLING'}
            aria-label={t('cancel')}
            onClick={() => void cancel(run.run_id)}
            variant="destructive"
            size="icon"
          />
        }
      >
        <Square size={14} />
      </TooltipTrigger>
      <TooltipContent>{t('cancel')}</TooltipContent>
    </Tooltip>
  );
}
