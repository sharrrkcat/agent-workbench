import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import type { PetPosition } from '../../types/settings';

export type Position = { x: number; y: number };
type Drag = { id: number; px: number; py: number; x: number; y: number };
type Options = {
  saved: PetPosition | null;
  width: number;
  height: number;
  onCommit: (position: PetPosition) => void | Promise<void>;
};

export function clampPosition(
  value: Position,
  width: number,
  height: number,
  viewport = { width: window.innerWidth, height: window.innerHeight },
): Position {
  const clamp = (coordinate: number, space: number) => {
    const available = Math.max(0, space);
    const margin = Math.min(8, available / 2);
    return Math.min(available - margin, Math.max(margin, Number.isFinite(coordinate) ? coordinate : 0));
  };
  return { x: clamp(value.x, viewport.width - width), y: clamp(value.y, viewport.height - height) };
}

export function usePetPosition({ saved, width, height, onCommit }: Options) {
  const [position, setPosition] = useState<Position>({ x: 0, y: 0 });
  const [drag, setDrag] = useState<Drag | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const applied = useRef('');
  const activeDrag = useRef<Drag | null>(null);
  const writeVersion = useRef(0);
  const commit = useRef(onCommit);
  commit.current = onCommit;

  useEffect(() => {
    if (!saved || drag) return;
    const signature = JSON.stringify([saved.mode, saved.x, saved.y, width, height]);
    if (applied.current === signature) return;
    applied.current = signature;
    const next = saved.mode === 'custom' && saved.x != null && saved.y != null
      ? { x: saved.x, y: saved.y }
      : { x: window.innerWidth - width - 28, y: window.innerHeight - height - 28 };
    setPosition(clampPosition(next, width, height));
  }, [saved, drag, width, height]);

  useEffect(() => {
    const onResize = () => setPosition((current) => clampPosition(current, width, height));
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [width, height]);

  useEffect(() => () => { writeVersion.current += 1; }, []);

  useEffect(() => {
    if (!drag) return;
    const nextPosition = (event: PointerEvent) => clampPosition(
      { x: drag.x + event.clientX - drag.px, y: drag.y + event.clientY - drag.py }, width, height,
    );
    const move = (event: PointerEvent) => {
      if (event.pointerId === activeDrag.current?.id) setPosition(nextPosition(event));
    };
    const up = (event: PointerEvent) => {
      if (event.pointerId !== activeDrag.current?.id) return;
      const next = nextPosition(event);
      activeDrag.current = null;
      setPosition(next);
      setDrag(null);
      setSaving(true);
      setError(null);
      const version = ++writeVersion.current;
      void Promise.resolve()
        .then(() => commit.current({ mode: 'custom', x: Math.round(next.x), y: Math.round(next.y) }))
        .catch((reason: unknown) => {
          if (version === writeVersion.current) setError(reason instanceof Error ? reason.message : String(reason));
        })
        .finally(() => { if (version === writeVersion.current) setSaving(false); });
    };
    const cancel = (event: PointerEvent) => {
      if (event.pointerId !== activeDrag.current?.id) return;
      activeDrag.current = null;
      setPosition(clampPosition({ x: drag.x, y: drag.y }, width, height));
      setDrag(null);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', cancel);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', cancel);
    };
  }, [drag, width, height]);

  function startDrag(event: ReactPointerEvent<HTMLElement>): boolean {
    if (!saved || event.button !== 0 || event.isPrimary === false || activeDrag.current) return false;
    event.preventDefault();
    const next = { id: event.pointerId, px: event.clientX, py: event.clientY, x: position.x, y: position.y };
    activeDrag.current = next;
    setDrag(next);
    return true;
  }
  return { position, dragging: drag !== null, saving, error, startDrag };
}
