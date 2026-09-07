import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { settingsApi } from '../../api/settings';
import type { PetSettings } from '../../types/settings';

export type Position = { x: number; y: number };
type Drag = { id: number; px: number; py: number; x: number; y: number };

export function clampPosition(
  value: Position,
  width: number,
  height: number,
  viewport = { width: window.innerWidth, height: window.innerHeight },
): Position {
  return {
    x: Math.min(Math.max(8, viewport.width - width - 8), Math.max(8, value.x || 0)),
    y: Math.min(Math.max(8, viewport.height - height - 8), Math.max(8, value.y || 0)),
  };
}

export function usePetPosition(settings: PetSettings | null, width: number, height: number) {
  const [position, setPosition] = useState<Position>({ x: 0, y: 0 });
  const [drag, setDrag] = useState<Drag | null>(null);
  const applied = useRef<{ saved: PetSettings['position']; width: number; height: number } | null>(null);

  useEffect(() => {
    if (!settings || drag) return;
    const saved = settings.position;
    if (applied.current?.saved === saved && applied.current.width === width && applied.current.height === height)
      return;
    const initial = applied.current === null;
    applied.current = { saved, width, height };
    setPosition((current) => {
      const next =
        saved.mode === 'custom' && saved.x != null && saved.y != null
          ? { x: saved.x, y: saved.y }
          : initial
            ? { x: window.innerWidth - width - 28, y: window.innerHeight - height - 92 }
            : current;
      return clampPosition(next, width, height);
    });
  }, [settings, drag, width, height]);

  useEffect(() => {
    const onResize = () => setPosition((current) => clampPosition(current, width, height));
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [width, height]);

  useEffect(() => {
    if (!drag) return;
    const nextPosition = (event: PointerEvent) =>
      clampPosition(
        {
          x: drag.x + event.clientX - drag.px,
          y: drag.y + event.clientY - drag.py,
        },
        width,
        height,
      );
    const move = (event: PointerEvent) => {
      if (event.pointerId === drag.id) setPosition(nextPosition(event));
    };
    const up = (event: PointerEvent) => {
      if (event.pointerId !== drag.id) return;
      const next = nextPosition(event);
      setPosition(next);
      setDrag(null);
      void settingsApi
        .updatePetSettings({ position: { mode: 'custom', x: Math.round(next.x), y: Math.round(next.y) } })
        .then(() => window.dispatchEvent(new Event('pet-settings-changed')))
        .catch(() => undefined);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
    };
  }, [drag, width, height]);

  function startDrag(event: ReactPointerEvent<HTMLDivElement>): boolean {
    if (event.button !== 0) return false;
    event.preventDefault();
    setDrag({ id: event.pointerId, px: event.clientX, py: event.clientY, x: position.x, y: position.y });
    return true;
  }
  return { position, dragging: drag !== null, startDrag };
}
