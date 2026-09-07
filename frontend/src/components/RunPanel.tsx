import { ChevronDown, Square } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { Run, RunStep } from '../types';

export function RunPanel({ run }: { run: Run }) {
  const { t } = useTranslation('runs');
  const cancel = useWorkbenchStore((state) => state.cancelRun);
  const resolveApproval = useWorkbenchStore((state) => state.resolveApproval);
  const resolving = useWorkbenchStore((state) => state.resolvingApprovals.includes(run.run_id));
  const messages = useWorkbenchStore((state) => state.messages);
  const storedSteps = useWorkbenchStore((state) => state.stepsByRunId[run.run_id]);
  const steps = storedSteps || run.steps || [];
  const [expanded, setExpanded] = useState(true);
  const active = ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(run.status);
  const approval = steps.find((step) => step.kind === 'approval' && step.status === 'running');
  const pending = messages.filter((message) => message.run_id === run.run_id).flatMap((message) => message.parts).find((part) => part.type === 'tool_call' && part.tool_call_id === approval?.metadata?.tool_call_id);
  return (
    <div className={`run-panel run-${run.status.toLowerCase()}`}>
      <div className="run-panel-header">
        <button type="button" className="run-expand" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}><ChevronDown size={15} className={expanded ? 'open' : ''} /> <strong>{statusLabel(run.status, t)}</strong></button>
        <span className="run-panel-actions">{run.status === 'WAITING_FOR_USER' && approval ? <><button type="button" className="secondary-button" disabled={resolving} onClick={() => void resolveApproval(run.run_id, 'reject')}>{t('reject')}</button><button type="button" className="primary-button" disabled={resolving} onClick={() => void resolveApproval(run.run_id, 'approve')}>{t(resolving ? 'resuming' : 'approve')}</button></> : null}{active ? <button type="button" className="icon-button danger" disabled={run.status === 'CANCELLING'} title={t('cancel')} aria-label={t('cancel')} onClick={() => void cancel(run.run_id)}><Square size={14} /></button> : null}</span>
      </div>
      {run.status === 'WAITING_FOR_USER' && pending?.type === 'tool_call' ? <div className="approval-details"><strong>{pending.tool_name}</strong><p>{t(`approvalRisk.${String(approval?.metadata?.risk || 'safe')}`)}</p><pre className="part-json">{JSON.stringify(pending.arguments, null, 2)}</pre></div> : null}
      {run.status === 'WAITING_FOR_USER' && typeof approval?.metadata?.service_url === 'string' ? <p>{t('service')}: {approval.metadata.service_url}</p> : null}
      {run.error ? <p className="run-error">{run.error_code ? `${run.error_code}: ` : ''}{run.error}</p> : null}
      {expanded ? <div className="run-steps">{steps.length ? [...steps].sort((a, b) => a.order - b.order).map((step) => <StepRow key={step.step_id} step={step} />) : <span className="run-muted">{t('preparing')}</span>}</div> : null}
    </div>
  );
}

function StepRow({ step }: { step: RunStep }) {
  const { t } = useTranslation('runs');
  const name = typeof step.metadata?.tool_name === 'string' ? step.metadata.tool_name : '';
  return <div className={`run-step step-${step.status}`} data-kind={step.kind}><span className="step-kind">{t(`stepKinds.${step.kind}`)}</span><span className="step-label">{name}</span><span className="step-status">{t(`stepStatus.${step.status}`)}</span>{step.error_message ? <small>{step.error_message}</small> : null}</div>;
}

function statusLabel(status: Run['status'], t: (key: string) => string): string {
  return ({ PENDING: t('queued'), RUNNING: t('running'), CANCELLING: t('cancelling'), WAITING_FOR_USER: t('waiting'), DONE: t('done'), FAILED: t('failed'), CANCELLED: t('cancelled'), INTERRUPTED: t('interrupted') } as Record<Run['status'], string>)[status];
}
