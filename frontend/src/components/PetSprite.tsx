import { useEffect, useMemo, useRef, useState } from 'react';

export type PetAnimationState =
  | 'idle'
  | 'running-right'
  | 'running-left'
  | 'waving'
  | 'jumping'
  | 'failed'
  | 'waiting'
  | 'running'
  | 'review';

type PetAnimationSpec = {
  row: number;
  durations: readonly number[];
  loop: boolean;
};

type PetSpriteProps = {
  spritesheetUrl: string;
  state: PetAnimationState;
  scale?: number;
  className?: string;
  repeatCount?: number;
  onAnimationLoopComplete?: (state: PetAnimationState, completedLoops: number) => void;
  onPlaybackComplete?: (state: PetAnimationState) => void;
};

export type PetSpriteState = PetAnimationState;

export const CODEX_PET_ATLAS = {
  columns: 8,
  rows: 9,
  frameWidth: 192,
  frameHeight: 208,
};

export const CODEX_PET_ANIMATIONS: Record<PetAnimationState, PetAnimationSpec> = {
  idle: {
    row: 0,
    durations: [560, 220, 220, 280, 280, 640],
    loop: true,
  },
  'running-right': {
    row: 1,
    durations: [120, 120, 120, 120, 120, 120, 120, 220],
    loop: true,
  },
  'running-left': {
    row: 2,
    durations: [120, 120, 120, 120, 120, 120, 120, 220],
    loop: true,
  },
  waving: {
    row: 3,
    durations: [140, 140, 140, 280],
    loop: false,
  },
  jumping: {
    row: 4,
    durations: [140, 140, 140, 140, 280],
    loop: false,
  },
  failed: {
    row: 5,
    durations: [140, 140, 140, 140, 140, 140, 140, 240],
    loop: true,
  },
  waiting: {
    row: 6,
    durations: [150, 150, 150, 150, 150, 260],
    loop: true,
  },
  running: {
    row: 7,
    durations: [120, 120, 120, 120, 120, 220],
    loop: true,
  },
  review: {
    row: 8,
    durations: [150, 150, 150, 150, 150, 280],
    loop: true,
  },
};

export function PetSprite({
  spritesheetUrl,
  state,
  scale = 1,
  className = '',
  repeatCount,
  onAnimationLoopComplete,
  onPlaybackComplete,
}: PetSpriteProps) {
  const [frame, setFrame] = useState(0);
  const reduceMotion = usePrefersReducedMotion();
  const loopCompleteRef = useRef(onAnimationLoopComplete);
  const playbackCompleteRef = useRef(onPlaybackComplete);
  const spec = CODEX_PET_ANIMATIONS[state];
  const renderSpec = reduceMotion ? CODEX_PET_ANIMATIONS.idle : spec;

  useEffect(() => {
    loopCompleteRef.current = onAnimationLoopComplete;
    playbackCompleteRef.current = onPlaybackComplete;
  }, [onAnimationLoopComplete, onPlaybackComplete]);

  useEffect(() => {
    const currentSpec = CODEX_PET_ANIMATIONS[state];
    setFrame(0);
    if (reduceMotion) return undefined;

    let cancelled = false;
    let timeoutId: number | undefined;
    const maxRepeats = repeatCount === undefined
      ? currentSpec.loop
        ? Number.POSITIVE_INFINITY
        : 1
      : Math.max(1, Math.floor(repeatCount));

    const tick = (currentFrame: number, completedLoops: number) => {
      const lastFrame = Math.max(0, currentSpec.durations.length - 1);
      const isLast = currentFrame >= lastFrame;
      const delay = currentSpec.durations[Math.min(currentFrame, lastFrame)] ?? 120;

      timeoutId = window.setTimeout(() => {
        if (cancelled) return;
        if (isLast) {
          const nextCompletedLoops = completedLoops + 1;
          loopCompleteRef.current?.(state, nextCompletedLoops);
          if (nextCompletedLoops < maxRepeats) {
            setFrame(0);
            tick(0, nextCompletedLoops);
            return;
          }
          playbackCompleteRef.current?.(state);
          return;
        }

        const nextFrame = currentFrame + 1;
        setFrame(nextFrame);
        tick(nextFrame, completedLoops);
      }, delay);
    };

    tick(0, 0);

    return () => {
      cancelled = true;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [state, spritesheetUrl, repeatCount, reduceMotion]);

  return (
    <div
      className={`pet-sprite-viewport ${className}`.trim()}
      data-state={state}
      data-frame={frame}
      style={{
        width: CODEX_PET_ATLAS.frameWidth * scale,
        height: CODEX_PET_ATLAS.frameHeight * scale,
      }}
      aria-hidden="true"
    >
      <img
        className="pet-sprite-sheet"
        src={spritesheetUrl}
        alt=""
        draggable={false}
        style={{
          width: CODEX_PET_ATLAS.frameWidth * CODEX_PET_ATLAS.columns * scale,
          height: CODEX_PET_ATLAS.frameHeight * CODEX_PET_ATLAS.rows * scale,
          transform: `translate(${-frame * CODEX_PET_ATLAS.frameWidth * scale}px, ${-renderSpec.row * CODEX_PET_ATLAS.frameHeight * scale}px)`,
        }}
      />
    </div>
  );
}

function usePrefersReducedMotion(): boolean {
  const [reduceMotion, setReduceMotion] = useState(() => (
    typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  ));

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onChange = () => setReduceMotion(media.matches);
    onChange();
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, []);

  return useMemo(() => reduceMotion, [reduceMotion]);
}
