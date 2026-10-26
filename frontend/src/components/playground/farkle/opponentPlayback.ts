import type { AiDecision } from './ai';
import type { TurnInput } from './state';

export const OPPONENT_TIMING = { think: 1500, select: 550, confirm: 900, handoff: 500 } as const;

/** A single settled roll, with a pausable clock independent of the calculation worker. */
export function createOpponentPlayback(emit: (input: TurnInput) => void, initiallyPaused: boolean, selected: readonly string[] = []) {
  let paused = initiallyPaused, disposed = false, thinking = true, finished = false;
  let decision: AiDecision | null = null;
  let index = 0;
  let remaining = 0, deadline = 0;
  let pending: (() => void) | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;

  function arm() {
    if (paused || disposed || !pending) return;
    deadline = performance.now() + remaining;
    timer = setTimeout(() => {
      timer = undefined;
      const next = pending!;
      pending = null;
      remaining = 0;
      next();
    }, remaining);
  }
  function wait(delay: number, next: () => void) {
    remaining = delay;
    pending = next;
    arm();
  }
  function advance() {
    if (thinking || !decision || paused || disposed || finished) return;
    if (index === decision.dice.length) {
      wait(OPPONENT_TIMING.confirm, () => { finished = true; emit({ type: decision!.action }); });
      return;
    }
    const id = decision.dice[index];
    emit({ type: 'hover', id });
    wait(OPPONENT_TIMING.select, () => { emit({ type: 'select', id }); index++; advance(); });
  }
  wait(OPPONENT_TIMING.think, () => { thinking = false; advance(); });

  return {
    setDecision(value: AiDecision) {
      decision = { ...value, dice: value.dice.filter((id) => !selected.includes(id)) };
      advance();
    },
    setPaused(value: boolean) {
      if (paused === value || disposed || finished) return;
      paused = value;
      if (paused) {
        if (timer !== undefined) {
          clearTimeout(timer);
          timer = undefined;
          remaining = Math.max(0, deadline - performance.now());
        }
      } else if (pending) arm();
      else advance();
    },
    dispose() { disposed = true; clearTimeout(timer); pending = null; },
  };
}
