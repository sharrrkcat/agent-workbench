import type { PetSettings } from '../../types/settings';
import type { Run, RunStep } from '../../types/runs';
import type { PetSpriteState } from '../PetSprite';

export function currentRun(runs: Run[], sessionId?: string): Run | null {
  return (
    [...runs]
      .filter((run) => run.session_id === sessionId)
      .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))
      .find((run) => ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(run.status)) ||
    [...runs]
      .filter(
        (run) => run.session_id === sessionId && ['DONE', 'FAILED', 'CANCELLED', 'INTERRUPTED'].includes(run.status),
      )
      .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))[0] ||
    null
  );
}

export function stateFor(run: Run | null, step: RunStep | null, hover: boolean, jumping: boolean): PetSpriteState {
  if (jumping) return 'jumping';
  if (hover) return 'idle';
  if (!run) return 'idle';
  if (run.status === 'WAITING_FOR_USER') return 'waiting';
  if (['PENDING', 'RUNNING', 'CANCELLING'].includes(run.status))
    return step?.kind === 'approval' ? 'waiting' : 'running';
  if (run.status === 'DONE') return 'review';
  if (['FAILED', 'CANCELLED', 'INTERRUPTED'].includes(run.status)) return 'failed';
  return 'idle';
}

export function bubbleFor(settings: PetSettings, run: Run | null, step: RunStep | null, stepLabel: string): string {
  if (!run) return settings.bubble_texts.idle;
  if (run.status === 'WAITING_FOR_USER' || step?.kind === 'approval') return settings.bubble_texts.waiting;
  if (['PENDING', 'RUNNING', 'CANCELLING'].includes(run.status))
    return `${settings.running_prefix}${stepLabel ? ` ${stepLabel}` : ''}`;
  if (run.status === 'DONE') return settings.bubble_texts.done;
  if (run.status === 'FAILED') return settings.bubble_texts.failed;
  if (run.status === 'CANCELLED') return settings.bubble_texts.cancelled;
  if (run.status === 'INTERRUPTED') return settings.bubble_texts.interrupted;
  return settings.bubble_texts.status;
}
