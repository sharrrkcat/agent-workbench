import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { ChevronDown } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useCogitaStore } from '../store/useCogitaStore';
import type { Run, RunStep } from '../types/runs';
import { RunApproval, RunCancelButton } from './messages/RunApproval';

export function RunPanel({ run }: { run: Run }) {
  const { t } = useTranslation('runs');
  const messages = useCogitaStore((state) => state.messages);
  const storedSteps = useCogitaStore((state) => state.stepsByRunId[run.run_id]);
  const steps = storedSteps || run.steps || [];
  const [expanded, setExpanded] = useState(true);
  const active = ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(run.status);
  return (
    <Collapsible
      open={expanded}
      onOpenChange={setExpanded}
      className={`run-panel run-${run.status.toLowerCase()}`}
    >
      <div className="run-panel-header">
        <CollapsibleTrigger render={<Button type="button" variant="ghost" className="run-expand" />}>
          <ChevronDown size={15} className={expanded ? '' : '-rotate-90'} />
          <strong>{statusLabel(run.status, t)}</strong>
        </CollapsibleTrigger>
        <span className="run-panel-actions">{active ? <RunCancelButton run={run} /> : null}</span>
      </div>
      <RunApproval run={run} steps={steps} messages={messages} />
      {run.error ? (
        <p className="run-error">
          {run.error_code ? `${run.error_code}: ` : ''}
          {run.error}
        </p>
      ) : null}
      <CollapsibleContent className="run-steps">
        {steps.length ? (
          [...steps]
            .sort((a, b) => a.order - b.order)
            .map((step) => <StepRow key={step.step_id} step={step} />)
        ) : (
          <span className="run-muted">{t('preparing')}</span>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}

function StepRow({ step }: { step: RunStep }) {
  const { t } = useTranslation('runs');
  const name = typeof step.metadata?.tool_name === 'string' ? step.metadata.tool_name : '';
  return (
    <div className={`run-step step-${step.status}`} data-kind={step.kind}>
      <span className="step-kind">{t(`stepKinds.${step.kind}`)}</span>
      <span className="step-label">{name}</span>
      <span className="step-status">{t(`stepStatus.${step.status}`)}</span>
      {step.error_message ? <small>{step.error_message}</small> : null}
    </div>
  );
}

function statusLabel(status: Run['status'], t: (key: string) => string): string {
  return (
    {
      PENDING: t('queued'),
      RUNNING: t('running'),
      CANCELLING: t('cancelling'),
      WAITING_FOR_USER: t('waiting'),
      DONE: t('done'),
      FAILED: t('failed'),
      CANCELLED: t('cancelled'),
      INTERRUPTED: t('interrupted'),
    } as Record<Run['status'], string>
  )[status];
}
