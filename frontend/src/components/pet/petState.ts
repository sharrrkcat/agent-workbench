import type { Run, RunStatus, RunStep, RunStepKind } from '../../types/runs';
import { older, terminal } from '../../store/workbench/mergeState';

export type PetTaskState = {
  run_id: string | null;
  status: RunStatus | 'IDLE';
  step_kind: RunStepKind | null;
  progress_message: string;
  progress_current: number | null;
  progress_total: number | null;
};

export function currentRun(runs: Run[], sessionId?: string): Run | null {
  if (!sessionId) return null;
  const ordered = runs.filter((run) => run.session_id === sessionId).sort((a, b) =>
    older(a.updated_at, b.updated_at) ? 1 : older(b.updated_at, a.updated_at) ? -1 : a.run_id.localeCompare(b.run_id),
  );
  return ordered.find((run) => !terminal(run.status)) || ordered[0] || null;
}

export function petTaskState(
  runs: Run[],
  stepsByRunId: Record<string, RunStep[]>,
  sessionId?: string,
): PetTaskState {
  const run = currentRun(runs, sessionId);
  if (!run) return { run_id: null, status: 'IDLE', step_kind: null, progress_message: '', progress_current: null, progress_total: null };
  const steps = stepsByRunId[run.run_id] ?? run.steps ?? [];
  const activeSteps = steps.filter((step) => step.run_id === run.run_id && step.status === 'running')
    .sort((a, b) => b.order - a.order);
  const step = terminal(run.status) ? null
    : (run.status === 'WAITING_FOR_USER' ? activeSteps.find((item) => item.kind === 'approval') : null) || activeSteps[0];
  return {
    run_id: run.run_id,
    status: run.status,
    step_kind: step?.kind ?? null,
    progress_message: run.progress_message || step?.message || '',
    progress_current: run.progress_current ?? null,
    progress_total: run.progress_total ?? null,
  };
}
