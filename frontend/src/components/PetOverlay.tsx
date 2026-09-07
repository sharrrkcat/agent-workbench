import { useMemo, useState, type CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';
import { API_BASE_URL, joinApiUrl } from '../api/url';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { PetSprite } from './PetSprite';
import { bubbleFor, currentRun, stateFor } from './pet/petState';
import { usePetData } from './pet/usePetData';
import { usePetPosition } from './pet/usePetPosition';

export function PetOverlay() {
  const { t } = useTranslation('runs');
  const { settings, pets } = usePetData();
  const [hover, setHover] = useState(false);
  const [jumping, setJumping] = useState(false);
  const session = useWorkbenchStore((state) => state.currentSession);
  const runs = useWorkbenchStore((state) => state.runs);
  const stepsByRunId = useWorkbenchStore((state) => state.stepsByRunId);
  const scale = settings?.pet_scale ?? 0.5;
  const width = 192 * scale;
  const height = 208 * scale;
  const { position, dragging, startDrag } = usePetPosition(settings, width, height);
  const pet = useMemo(() => {
    const valid = pets.filter((item) => item.valid && item.spritesheet_url);
    return valid.find((item) => item.id === settings?.default_pet_id) || valid[0] || null;
  }, [pets, settings?.default_pet_id]);
  const current = useMemo(() => currentRun(runs, session?.session_id), [runs, session?.session_id]);
  const step = current
    ? (stepsByRunId[current.run_id] || current.steps || []).find((item) => item.status === 'running') || null
    : null;
  const spriteState = stateFor(current, step, hover, jumping);
  if (!settings?.pet_enabled || !pet?.spritesheet_url) return null;
  const bubble = bubbleFor(settings, current, step, step ? t(`stepKinds.${step.kind}`) : '');

  return (
    <div
      className="pet-overlay"
      aria-label={pet.display_name}
      style={
        {
          left: position.x,
          top: position.y,
          width,
          height,
          '--pet-bubble-offset-x': `${settings.bubble_offset_x}px`,
          '--pet-bubble-offset-y': `${settings.bubble_offset_y}px`,
        } as CSSProperties
      }
      onPointerDown={(event) => {
        if (startDrag(event)) {
          setHover(false);
          setJumping(false);
        }
      }}
      onPointerEnter={() => {
        setHover(true);
        if (settings.jump_on_hover) setJumping(true);
      }}
      onPointerLeave={() => {
        setHover(false);
        setJumping(false);
      }}
    >
      {settings.show_status_bubble && bubble && !dragging ? <div className="pet-status-bubble">{bubble}</div> : null}
      <PetSprite
        spritesheetUrl={joinApiUrl(API_BASE_URL, pet.spritesheet_url)}
        state={spriteState}
        scale={scale}
        className="pet-sprite"
        repeatCount={spriteState === 'jumping' ? 1 : undefined}
        onPlaybackComplete={() => setJumping(false)}
      />
    </div>
  );
}
