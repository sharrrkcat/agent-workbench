import { ChevronDown, Square } from 'lucide-react';
import { useState } from 'react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { Run, RunStep } from '../types';

export function RunPanel({ run }: { run: Run }) {
  const cancel = useWorkbenchStore((state) => state.cancelRun);
  const steps = useWorkbenchStore((state) => state.stepsByRunId[run.run_id] || run.steps || []);
  const [expanded, setExpanded] = useState(true);
  const active = ['PENDING', 'RUNNING', 'CANCELLING'].includes(run.status);
  return (
    <div className={`run-panel run-${run.status.toLowerCase()}`}>
      <div className="run-panel-header">
        <button type="button" className="run-expand" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}><ChevronDown size={15} className={expanded ? 'open' : ''} /> <strong>{statusLabel(run.status)}</strong></button>
        {active ? <button type="button" className="icon-button danger" title="Cancel" aria-label="Cancel" onClick={() => void cancel(run.run_id)}><Square size={14} /></button> : null}
      </div>
      {run.error ? <p className="run-error">{run.error_code ? `${run.error_code}: ` : ''}{run.error}</p> : null}
      {expanded ? <div className="run-steps">{steps.length ? steps.sort((a, b) => a.order - b.order).map((step) => <StepRow key={step.step_id} step={step} />) : <span className="run-muted">Preparing…</span>}</div> : null}
    </div>
  );
}

function StepRow({ step }: { step: RunStep }) {
  return <div className={`run-step step-${step.status}`} data-kind={step.kind}><span className="step-kind">{step.kind}</span><span className="step-label">{step.label || step.kind}</span><span className="step-status">{step.status}</span>{step.error_message ? <small>{step.error_message}</small> : null}</div>;
}

function statusLabel(status: Run['status']): string {
  return ({ PENDING: 'Queued', RUNNING: 'Running', CANCELLING: 'Cancelling', WAITING_FOR_USER: 'Waiting for confirmation', DONE: 'Done', FAILED: 'Failed', CANCELLED: 'Cancelled', INTERRUPTED: 'Interrupted' } as Record<Run['status'], string>)[status];
}
