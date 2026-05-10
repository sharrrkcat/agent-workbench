import { useEffect, useState } from 'react';

export type PetSpriteState =
  | 'idle'
  | 'running-right'
  | 'running-left'
  | 'waving'
  | 'jumping'
  | 'failed'
  | 'waiting'
  | 'running'
  | 'review';

type PetSpriteProps = {
  spritesheetUrl: string;
  state: PetSpriteState;
  scale?: number;
  className?: string;
};

const COLS = 8;
const ROWS = 9;
const FRAME_WIDTH = 192;
const FRAME_HEIGHT = 208;
const FRAME_INTERVAL_MS = 120;

const STATE_ROW: Record<PetSpriteState, number> = {
  idle: 0,
  'running-right': 1,
  'running-left': 2,
  waving: 3,
  jumping: 4,
  failed: 5,
  waiting: 6,
  running: 7,
  review: 8,
};

export function PetSprite({ spritesheetUrl, state, scale = 1, className = '' }: PetSpriteProps) {
  const [frame, setFrame] = useState(0);
  const row = STATE_ROW[state];

  useEffect(() => {
    setFrame(0);
    const timer = window.setInterval(() => {
      setFrame((value) => (value + 1) % COLS);
    }, FRAME_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [state, spritesheetUrl]);

  return (
    <div
      className={`pet-sprite-viewport ${className}`.trim()}
      data-state={state}
      style={{
        width: FRAME_WIDTH * scale,
        height: FRAME_HEIGHT * scale,
      }}
      aria-hidden="true"
    >
      <img
        className="pet-sprite-sheet"
        src={spritesheetUrl}
        alt=""
        draggable={false}
        style={{
          width: FRAME_WIDTH * COLS * scale,
          height: FRAME_HEIGHT * ROWS * scale,
          transform: `translate(${-frame * FRAME_WIDTH * scale}px, ${-row * FRAME_HEIGHT * scale}px)`,
        }}
      />
    </div>
  );
}
