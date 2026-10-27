import { useCallback, useEffect, useLayoutEffect, useRef, useState, type Dispatch } from 'react';
import { useTranslation } from 'react-i18next';
import { Dice1, Dice2, Dice3, Dice4, Dice5, Dice6 } from 'lucide-react';
import { Vector3 } from 'three';
import { Button } from '@/components/ui/button';
import { initialPosition, placeCamera, tableLayout } from './layout';
import { DiceScene, type HitBounds } from './scene';
import { nextHoveredDie, type Direction } from './input';
import { FarkleHud } from './FarkleHud';
import { TurnNotice } from './TurnNotice';
import { pickTrajectory, type Trajectory } from './playback';
import { canHumanPlay, canPlay, type GameAction, type GameState, type TurnInput } from './state';
import { rollValues } from './dice';
import { DEVIL_HEAD_PATH } from './materials';
import { isWild } from './scoring';
import { OPPONENT_TIMING } from './opponentPlayback';
import rolls from './rolls.json';

const faceIcons = [Dice1, Dice2, Dice3, Dice4, Dice5, Dice6];
const hoverQuery = '(hover: hover) and (pointer: fine)';

export function FarkleTable({ state, dispatch, onReady, blocked, onNewGame }: {
  state: GameState; dispatch: Dispatch<GameAction>; onReady: (ready: boolean) => void; blocked: boolean;
  onNewGame: (source: HTMLElement) => void;
}) {
  const { t } = useTranslation('common');
  const container = useRef<HTMLDivElement>(null);
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const bounds = useRef(new Map<string, HitBounds>());
  const faceIcon = useRef<HTMLDivElement>(null);
  const apply = useRef<(state: GameState) => void>(() => {});
  const [failed, setFailed] = useState(false);
  const [canHover, setCanHover] = useState(() => window.matchMedia(hoverQuery).matches);
  const [touchHintId, setTouchHintId] = useState<string | null>(null);
  const hoverEnabled = useRef(canHover);
  hoverEnabled.current = canHover;
  const inputBlocked = useRef(blocked);
  inputBlocked.current = blocked;
  const disabled = !canHumanPlay(state) || blocked;
  const hovered = canPlay(state) && !blocked && (state.player === 'A' || canHover)
    ? state.dice.find((die) => die.id === state.hoverId) : undefined;
  const touched = !disabled && !canHover
    ? state.dice.find((die) => die.id === touchHintId && die.status === 'selected') : undefined;
  const hinted = hovered ?? touched;
  const hintId = useRef<string | undefined>(undefined);
  hintId.current = hinted?.id;
  const FaceIcon = faceIcons[(hinted?.value ?? 1) - 1];
  const play = useCallback((input: TurnInput) => dispatch({ ...input, actor: 'human' }), [dispatch]);

  useEffect(() => {
    const query = window.matchMedia(hoverQuery);
    const update = () => setCanHover(query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  useEffect(() => { if (!canHover) play({ type: 'hover', id: null }); }, [canHover, play]);
  useEffect(() => { setTouchHintId(null); }, [state.revision, canHover]);

  useEffect(() => {
    function keydown(event: KeyboardEvent) {
      if (disabled || failed || event.defaultPrevented || event.isComposing
        || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.target instanceof Element && event.target.closest('input, textarea, select, [contenteditable="true"], [role="textbox"]')) return;
      const key = event.key.toLowerCase();
      if (['w', 'a', 's', 'd'].includes(key)) {
        event.preventDefault();
        setCanHover(true);
        const points = state.dice.filter((die) => die.player === state.player && die.status !== 'scored').map((die) => {
          const point = bounds.current.get(die.id)!;
          return { id: die.id, index: die.index, x: point.centerX, y: point.centerY };
        });
        play({ type: 'hover', id: nextHoveredDie(points, state.hoverId, key as Direction) });
      } else if (key === 'e' || key === 'f' || key === 'q') {
        event.preventDefault();
        if (event.repeat) return;
        setCanHover(true);
        if (key === 'e' && state.hoverId && canHover) play({ type: 'select', id: state.hoverId });
        if (key === 'f') play({ type: 'store' });
        if (key === 'q') play({ type: 'pass' });
      }
    }
    window.addEventListener('keydown', keydown);
    return () => window.removeEventListener('keydown', keydown);
  }, [state, play, disabled, failed, canHover]);

  useLayoutEffect(() => {
    const host = container.current!;
    let current: GameState | null = null;
    let scene: DiceScene;
    try {
      scene = new DiceScene(host, (position) => {
        const { id, left, top, width, height } = position;
        bounds.current.set(id, position);
        const button = buttons.current.get(id);
        if (button) Object.assign(button.style, {
          left: `${left}px`, top: `${top}px`, width: `${width}px`, height: `${height}px`,
          visibility: left >= host.clientWidth || left + width <= 0 || top >= host.clientHeight || top + height <= 0 ? 'hidden' : 'visible',
        });
        if (id === hintId.current && faceIcon.current) Object.assign(faceIcon.current.style, {
          left: `${position.iconX}px`, top: `${position.iconY}px`,
        });
      });
    } catch (error) {
      console.error('Farkle renderer initialization failed', error);
      setFailed(true);
      onReady(false);
      return;
    }
    let layout = tableLayout(Math.max(1, host.clientWidth), Math.max(1, host.clientHeight));
    let commandId = -1;
    const moves = new Map<string, Vector3>();
    const recent = new Map<number, number[]>();
    const target = layout.views.B.clone();
    let viewProgress = 1;
    let live = true;
    let turnTimer: ReturnType<typeof setTimeout> | undefined;

    function frameCamera() {
      const command = current?.command;
      if (command?.kind === 'view') target.lerpVectors(layout.views[command.from], layout.views[command.to], viewProgress);
      else target.copy(layout.views[current?.player ?? 'B']);
      placeCamera(scene.camera, layout, target);
    }
    function resize() {
      if (!host.clientWidth || !host.clientHeight) return;
      layout = tableLayout(host.clientWidth, host.clientHeight);
      for (const die of current?.dice ?? []) scene.setOrigin(die.id, layout.origins[die.player]);
      if (current) for (const player of ['A', 'B'] as const) {
        current.batches[player].forEach((batch, row) => batch.forEach((id, column) => {
          scene.setPosition(id, layout.slot(player, row, column, batch.length));
        }));
      }
      const command = current?.command;
      if (command?.kind === 'store') command.dice.forEach((id, column) => {
        moves.get(id)!.copy(layout.slot(current!.player, current!.batches[current!.player].length, column, command.dice.length));
      });
      frameCamera();
      scene.resize(host.clientWidth, host.clientHeight, Math.max(200, layout.distance * 4));
    }
    apply.current = (next) => {
      current = next;
      const command = next.command;
      if (command && command.id !== commandId) {
        commandId = command.id;
        clearTimeout(turnTimer);
        moves.clear();
        const complete = () => {
          if (live) dispatch({ type: 'complete', id: command.id,
            values: rollValues(next.dice.filter((die) => die.player === next.player).map((die) => die.type)),
            hoverSample: next.player === 'B' && hoverEnabled.current ? Math.random() : null });
        };
        if (command.kind === 'reset') {
          moves.clear(); bounds.current.clear(); recent.clear();
          scene.reset(next.dice.map((die) => ({ id: die.id, type: die.type,
            origin: layout.origins[die.player], position: initialPosition(die.index) })));
          frameCamera();
          complete();
        } else if (command.kind === 'store') {
          command.dice.forEach((id, column) => moves.set(id,
            layout.slot(next.player, next.batches[next.player].length, column, command.dice.length)));
          scene.moveBatch([...moves].map(([id, position]) => ({ id, position })), complete);
        } else if (command.kind === 'view') {
          viewProgress = 0;
          scene.animate((elapsed) => {
            const u = Math.min(1, elapsed / 500);
            viewProgress = u * u * (3 - 2 * u);
            frameCamera();
            return u === 1;
          }, complete);
        } else if (command.kind === 'bust') {
          turnTimer = setTimeout(complete, 1200);
        } else if (command.kind === 'turnEnd') {
          turnTimer = setTimeout(complete, OPPONENT_TIMING.handoff);
        } else {
          const pool: Trajectory[] = (rolls.pools as Record<number, Trajectory[]>)[command.dice.length];
          scene.roll(pickTrajectory(pool, recent), command.dice, complete);
        }
      }
      scene.setIndicators(canPlay(next) ? next.dice.filter((die) => die.player === next.player && die.status === 'selected').map((die) => die.id) : [],
        !canPlay(next) || inputBlocked.current || (next.player === 'B' && !hoverEnabled.current) ? null : next.hoverId, next.player);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    resize();
    onReady(true);
    return () => {
      live = false;
      clearTimeout(turnTimer);
      apply.current = () => {};
      observer.disconnect();
      bounds.current.clear();
      scene.dispose();
    };
  }, [dispatch, onReady]);

  useLayoutEffect(() => { apply.current(state); }, [state, canHover, blocked, hinted?.id]);
  return <div ref={container} className="farkle-table relative min-h-0 flex-1 overflow-hidden" aria-label={t('farkle.table')}
    data-player={state.player} data-view={state.player} data-busy={state.busy}
    data-phase={state.winner ? 'finished' : state.command?.kind ?? 'idle'} onPointerDown={(event) => {
      if (event.pointerType === 'touch') { setCanHover(false); play({ type: 'hover', id: null }); }
      else if (!disabled && event.pointerType === 'mouse') setCanHover(true);
    }} onPointerMove={(event) => {
      if (!disabled && event.pointerType === 'mouse') setCanHover(true);
    }}>
    {failed ? <div className="absolute inset-0 flex items-center justify-center p-6" role="alert">{t('farkle.renderError')}</div> : <>
      {state.dice.filter((die) => die.player === state.player).map((die) => <Button key={die.id}
        ref={(element) => { if (element) buttons.current.set(die.id, element); else buttons.current.delete(die.id); }}
        type="button" variant="ghost" className="farkle-die-hit absolute min-h-0 min-w-0 p-0 opacity-0 transition-none active:not-aria-[haspopup]:translate-y-0 focus-visible:opacity-100 disabled:opacity-0 pointer-coarse:min-h-0 pointer-coarse:min-w-0"
        disabled={disabled || die.status === 'scored'}
        aria-label={t(die.status === 'scored' ? 'farkle.scoredDie' : die.status === 'selected' ? 'farkle.releaseDie' : 'farkle.holdDie', {
          player: die.player, number: die.index + 1,
          value: isWild(die) ? t('farkle.wildFace') : t('farkle.faceValue', { value: die.value }), name: t(`farkle.dice.${die.type}`),
        })}
        data-die-id={die.id} data-die-type={die.type} data-value={die.value} data-state={die.status} data-hovered={hovered?.id === die.id}
        data-batch={state.batches[die.player].findIndex((batch) => batch.includes(die.id))}
        aria-pressed={die.status === 'selected'}
        onPointerMove={(event) => {
          if (!disabled && event.pointerType === 'mouse') play({ type: 'hover', id: die.id });
        }}
        onFocus={() => { if (canHover) play({ type: 'hover', id: die.id }); }}
        onClick={() => {
          if (canHover) play({ type: 'hover', id: die.id });
          else setTouchHintId(die.status === 'selected' ? null : die.id);
          play({ type: 'select', id: die.id });
        }} />)}
      {hinted ? <div ref={faceIcon} className="farkle-face-icon" aria-hidden="true"
        data-hint-die-id={hinted.id} data-hint-source={touched ? 'touch' : 'hover'} data-face-value={isWild(hinted) ? 'wild' : hinted.value}>
        {isWild(hinted) ? <svg viewBox="0 0 100 100" className="farkle-head-icon"><path d={DEVIL_HEAD_PATH} fillRule="evenodd" /></svg> : <FaceIcon />}
        {touched || hinted.type !== 'normal' ? <span className="farkle-die-name">{t(`farkle.dice.${hinted.type}`)}</span> : null}
      </div> : null}
      {state.command?.kind === 'bust' ? <div className="farkle-bust" role="status">
        <div className="farkle-score-heading">{t('farkle.bust')}</div>
      </div> : null}
      {state.playing ? <FarkleHud state={state} disabled={disabled}
        onHold={() => { if (state.hoverId) play({ type: 'select', id: state.hoverId }); }}
        onStore={() => play({ type: 'store' })} onPass={() => play({ type: 'pass' })} /> : null}
      <TurnNotice state={state} />
    </>}
    {(!state.playing || state.winner) && !blocked ? <Button variant="ghost"
      className="absolute inset-0 h-full w-full opacity-0 focus-visible:opacity-100" aria-label={t('farkle.newGame')}
      data-table-new-game onClick={(event) => onNewGame(event.currentTarget)} /> : null}
  </div>;
}
