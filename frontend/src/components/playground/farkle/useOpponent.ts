import { useEffect, useLayoutEffect, useRef, useState, type Dispatch } from 'react';
import type { AiRequest, AiResponse } from './ai.worker';
import { createOpponentPlayback } from './opponentPlayback';
import { canPlay, type GameAction, type GameState } from './state';

export function useOpponent(state: GameState, dispatch: Dispatch<GameAction>, blocked: boolean) {
  const worker = useRef<Worker | null>(null);
  const playback = useRef<{ id: number; run: ReturnType<typeof createOpponentPlayback> } | null>(null);
  const latest = useRef({ state, blocked });
  latest.current = { state, blocked };
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!state.matchId || state.winner) return;
    setFailed(false);
    const instance = new Worker(new URL('./ai.worker.ts', import.meta.url), { type: 'module' });
    worker.current = instance;
    instance.onmessage = (event: MessageEvent<AiResponse>) => {
      const current = playback.current;
      if (current?.id === event.data.id) current.run.setDecision(event.data.decision);
    };
    instance.onerror = (event) => {
      console.error('Farkle opponent calculation failed', event.message);
      playback.current?.run.dispose();
      setFailed(true);
    };
    instance.postMessage({ kind: 'prepare', types: latest.current.state.dice.filter((die) => die.player === 'A').map((die) => die.type) } satisfies AiRequest);
    return () => { instance.onmessage = null; instance.onerror = null; instance.terminate(); worker.current = null; };
  }, [state.matchId, state.winner, attempt]);

  const id = canPlay(state) && state.player === 'A' ? state.revision : null;
  useEffect(() => {
    if (id === null || failed || !worker.current) return;
    const current = latest.current;
    const run = createOpponentPlayback((input) => dispatch({ ...input, actor: 'ai', revision: id }),
      current.blocked || document.hidden, current.state.dice.filter((die) => die.player === 'A' && die.status === 'selected').map((die) => die.id));
    playback.current = { id, run };
    worker.current.postMessage({ kind: 'decide', id, position: {
      target: current.state.target, banked: current.state.totals.A, round: current.state.rounds.A,
      dice: current.state.dice.filter((die) => die.player === 'A'),
    } } satisfies AiRequest);
    return () => { run.dispose(); playback.current = null; };
  }, [id, failed, attempt, dispatch]);

  useLayoutEffect(() => { playback.current?.run.setPaused(blocked || document.hidden); }, [blocked]);
  useEffect(() => {
    const visibility = () => playback.current?.run.setPaused(latest.current.blocked || document.hidden);
    document.addEventListener('visibilitychange', visibility);
    return () => document.removeEventListener('visibilitychange', visibility);
  }, []);

  return { failed, retry: () => setAttempt((value) => value + 1) };
}
