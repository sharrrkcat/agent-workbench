import { useEffect, useState } from 'react';

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
  frameCount: number;
  frameDurationMs: number;
  lastFrameDurationMs?: number;
  loop: boolean;
};

type PetSpriteProps = {
  spritesheetUrl: string;
  state: PetAnimationState;
  scale?: number;
  className?: string;
  onAnimationComplete?: (state: PetAnimationState) => void;
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
    frameCount: 6,
    frameDurationMs: 160,
    lastFrameDurationMs: 360,
    loop: true,
  },
  'running-right': {
    row: 1,
    frameCount: 8,
    frameDurationMs: 90,
    loop: true,
  },
  'running-left': {
    row: 2,
    frameCount: 8,
    frameDurationMs: 90,
    loop: true,
  },
  waving: {
    row: 3,
    frameCount: 4,
    frameDurationMs: 140,
    lastFrameDurationMs: 260,
    loop: false,
  },
  jumping: {
    row: 4,
    frameCount: 5,
    frameDurationMs: 110,
    lastFrameDurationMs: 180,
    loop: false,
  },
  failed: {
    row: 5,
    frameCount: 8,
    frameDurationMs: 150,
    lastFrameDurationMs: 300,
    loop: true,
  },
  waiting: {
    row: 6,
    frameCount: 6,
    frameDurationMs: 170,
    lastFrameDurationMs: 360,
    loop: true,
  },
  running: {
    row: 7,
    frameCount: 6,
    frameDurationMs: 120,
    loop: true,
  },
  review: {
    row: 8,
    frameCount: 6,
    frameDurationMs: 150,
    lastFrameDurationMs: 300,
    loop: true,
  },
};

export function PetSprite({ spritesheetUrl, state, scale = 1, className = '', onAnimationComplete }: PetSpriteProps) {
  const [frame, setFrame] = useState(0);
  const spec = CODEX_PET_ANIMATIONS[state];

  useEffect(() => {
    const currentSpec = CODEX_PET_ANIMATIONS[state];
    setFrame(0);
    let cancelled = false;
    let timeoutId: number | undefined;

    const tick = (currentFrame: number) => {
      const lastFrame = Math.max(0, currentSpec.frameCount - 1);
      const isLast = currentFrame >= lastFrame;
      const delay = isLast
        ? currentSpec.lastFrameDurationMs ?? currentSpec.frameDurationMs
        : currentSpec.frameDurationMs;

      timeoutId = window.setTimeout(() => {
        if (cancelled) return;
        if (isLast) {
          if (currentSpec.loop) {
            setFrame(0);
            tick(0);
          } else {
            onAnimationComplete?.(state);
          }
          return;
        }

        const nextFrame = currentFrame + 1;
        setFrame(nextFrame);
        tick(nextFrame);
      }, delay);
    };

    tick(0);

    return () => {
      cancelled = true;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [state, spritesheetUrl, onAnimationComplete]);

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
          transform: `translate(${-frame * CODEX_PET_ATLAS.frameWidth * scale}px, ${-spec.row * CODEX_PET_ATLAS.frameHeight * scale}px)`,
        }}
      />
    </div>
  );
}
