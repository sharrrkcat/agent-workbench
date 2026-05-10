import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react';
import { API_BASE_URL, api, joinApiUrl } from '../api/client';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { PetBubbleTexts, PetItem, PetSettings, Run, RunStep } from '../types';
import { PetSprite, type PetSpriteState } from './PetSprite';

type DragState = {
  pointerId: number;
  startPointerX: number;
  startPointerY: number;
  startX: number;
  startY: number;
  lastX: number;
};

const BASE_WIDTH = 192;
const BASE_HEIGHT = 208;
const DEFAULT_MARGIN_RIGHT = 28;
const DEFAULT_MARGIN_BOTTOM = 92;
const TERMINAL_HOLD_MS = 4200;
const PET_REFRESH_MS = 6000;

const PET_RUN_STEP_TASK_LABELS: Record<string, string> = {
  'Resolving agent': '\u51c6\u5907\u4ee3\u7406',
  'Building context': '\u6574\u7406\u4e0a\u4e0b\u6587',
  'Resolving model': '\u51c6\u5907\u6a21\u578b',
  'Calling LLM': '\u8c03\u7528\u6a21\u578b',
  'Starting script': '\u542f\u52a8\u811a\u672c',
  'Running script': '\u8fd0\u884c\u811a\u672c',
  'Saving response': '\u4fdd\u5b58\u56de\u590d',
  Cleanup: '\u6e05\u7406\u8d44\u6e90',
};

const DEFAULT_BUBBLE_TEXTS: PetBubbleTexts = {
  idle: '',
  waiting: '\u7b49\u4f60\u4e00\u4e0b',
  done: '\u5b8c\u6210\u5566',
  failed: '\u51fa\u9519\u4e86',
  cancelled: '\u5df2\u53d6\u6d88',
  interrupted: '\u5df2\u4e2d\u65ad',
  wake: '\u6211\u6765\u5566',
  tuck: '\u5148\u7761\u4e00\u4f1a\u513f',
  status: '\u6211\u5728\u8fd9\u91cc',
  select: '\u6362\u597d\u5566',
  reload: '\u91cd\u65b0\u626b\u63cf\u5b8c\u6210',
  no_pet: '\u8fd8\u6ca1\u6709\u53ef\u7528\u7684\u5ba0\u7269',
  import_success: '\u5bfc\u5165\u6210\u529f',
  import_failed: '\u5bfc\u5165\u5931\u8d25',
  delete_success: '\u5df2\u5220\u9664',
  delete_failed: '\u5220\u9664\u5931\u8d25',
};

const DEFAULT_SETTINGS: PetSettings = {
  pet_enabled: true,
  default_pet_id: '',
  pet_scale: 1,
  show_status_bubble: true,
  bubble_offset_x: 12,
  bubble_offset_y: -12,
  jump_on_hover: true,
  running_prefix: '\u6b63\u5728',
  position: { mode: 'default', x: null, y: null },
  bubble_texts: DEFAULT_BUBBLE_TEXTS,
};

export function PetOverlay() {
  const { currentSession, runs, stepsByRunId } = useWorkbenchStore();
  const [settings, setSettings] = useState<PetSettings | null>(null);
  const [pets, setPets] = useState<PetItem[]>([]);
  const [position, setPosition] = useState<{ x: number; y: number } | null>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const [dragDirection, setDragDirection] = useState<'left' | 'right'>('right');
  const [jumping, setJumping] = useState(false);
  const [terminalRun, setTerminalRun] = useState<Run | null>(null);
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const lastHeldTerminalRunIdRef = useRef<string | null>(null);

  const validPets = useMemo(() => pets.filter((pet) => pet.valid && pet.spritesheet_url), [pets]);
  const selectedPet = useMemo(() => {
    if (!validPets.length || !settings) return null;
    return validPets.find((pet) => pet.id === settings.default_pet_id) || validPets[0];
  }, [settings, validPets]);

  const scale = clampNumber(settings?.pet_scale || 1, 0.5, 2);
  const petWidth = BASE_WIDTH * scale;
  const petHeight = BASE_HEIGHT * scale;
  const activeRun = useMemo(() => pickActiveRun(runs, currentSession?.session_id), [runs, currentSession?.session_id]);
  const baseRun = activeRun || terminalRun;
  const baseState = useMemo(() => mapRunToPetState(baseRun), [baseRun]);
  const animationState: PetSpriteState = drag
    ? dragDirection === 'left'
      ? 'running-left'
      : 'running-right'
    : jumping
      ? 'jumping'
      : baseState;
  const runningStep = useMemo(() => (activeRun ? pickRunningStep(stepsByRunId[activeRun.run_id] || activeRun.steps || []) : null), [activeRun, stepsByRunId]);
  const bubbleText = settings ? buildBubbleText(settings, activeRun, terminalRun, runningStep) : '';
  const spriteUrl = selectedPet?.spritesheet_url ? joinApiUrl(API_BASE_URL, selectedPet.spritesheet_url) : '';

  const refreshPetState = useCallback(async (cancelled: () => boolean = () => false) => {
    try {
      const [settingsResponse, petsResponse] = await Promise.all([api.getPetSettings(), api.listPets()]);
      if (cancelled()) return;
      const nextSettings = normalizeSettings(settingsResponse.settings);
      setSettings(nextSettings);
      setPets(petsResponse.pets);
      setPosition((current) => current || resolveInitialPosition(nextSettings, BASE_WIDTH * nextSettings.pet_scale, BASE_HEIGHT * nextSettings.pet_scale));
    } catch {
      if (!cancelled()) {
        setSettings(null);
        setPets([]);
      }
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void refreshPetState(() => cancelled);
    const timer = window.setInterval(() => void refreshPetState(() => cancelled), PET_REFRESH_MS);
    const onFocus = () => void refreshPetState(() => cancelled);
    window.addEventListener('focus', onFocus);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener('focus', onFocus);
    };
  }, [refreshPetState]);

  useEffect(() => {
    if (!settings || drag) return;
    setPosition((current) => {
      const base = settings.position.mode === 'custom' && typeof settings.position.x === 'number' && typeof settings.position.y === 'number'
        ? { x: settings.position.x, y: settings.position.y }
        : current || defaultPosition(petWidth, petHeight);
      return clampPosition(base, petWidth, petHeight);
    });
  }, [petWidth, petHeight, settings?.position.mode, settings?.position.x, settings?.position.y, drag]);

  useEffect(() => {
    if (!activeRun) return;
    setTerminalRun(null);
  }, [activeRun?.run_id]);

  useEffect(() => {
    if (activeRun) return;
    const latestTerminal = pickLatestTerminalRun(runs, currentSession?.session_id);
    if (!latestTerminal || latestTerminal.run_id === terminalRun?.run_id || latestTerminal.run_id === lastHeldTerminalRunIdRef.current) return;
    setTerminalRun(latestTerminal);
  }, [activeRun, currentSession?.session_id, runs, terminalRun?.run_id]);

  useEffect(() => {
    if (!terminalRun || activeRun) return;
    const timer = window.setTimeout(() => {
      lastHeldTerminalRunIdRef.current = terminalRun.run_id;
      setTerminalRun((current) => (current?.run_id === terminalRun.run_id ? null : current));
    }, TERMINAL_HOLD_MS);
    return () => window.clearTimeout(timer);
  }, [activeRun, terminalRun]);

  useEffect(() => {
    if (!drag) return;
    const onPointerMove = (event: PointerEvent) => {
      if (event.pointerId !== drag.pointerId) return;
      const next = clampPosition(
        {
          x: drag.startX + event.clientX - drag.startPointerX,
          y: drag.startY + event.clientY - drag.startPointerY,
        },
        petWidth,
        petHeight,
      );
      setDragDirection(event.clientX < drag.lastX ? 'left' : 'right');
      setDrag((current) => (current ? { ...current, lastX: event.clientX } : current));
      setPosition(next);
    };
    const onPointerUp = (event: PointerEvent) => {
      if (event.pointerId !== drag.pointerId) return;
      const finalPosition = clampPosition(position || defaultPosition(petWidth, petHeight), petWidth, petHeight);
      setDrag(null);
      setPosition(finalPosition);
      void api.updatePetSettings({ position: { mode: 'custom', x: Math.round(finalPosition.x), y: Math.round(finalPosition.y) } }).then((response) => {
        setSettings(normalizeSettings(response.settings));
      }).catch(() => undefined);
    };
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    window.addEventListener('pointercancel', onPointerUp);
    return () => {
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
      window.removeEventListener('pointercancel', onPointerUp);
    };
  }, [drag, petHeight, petWidth, position]);

  useEffect(() => {
    const onResize = () => {
      setPosition((current) => clampPosition(current || defaultPosition(petWidth, petHeight), petWidth, petHeight));
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [petHeight, petWidth]);

  const startJump = useCallback(() => {
    if (!settings?.jump_on_hover || drag) return;
    setJumping(true);
  }, [drag, settings?.jump_on_hover]);

  const handleAnimationComplete = useCallback((state: PetSpriteState) => {
    if (state === 'jumping') {
      setJumping(false);
    }
  }, []);

  function startDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || !position) return;
    event.preventDefault();
    overlayRef.current?.setPointerCapture(event.pointerId);
    setJumping(false);
    setDrag({
      pointerId: event.pointerId,
      startPointerX: event.clientX,
      startPointerY: event.clientY,
      startX: position.x,
      startY: position.y,
      lastX: event.clientX,
    });
  }

  if (!settings?.pet_enabled || !selectedPet || !spriteUrl || !position) return null;

  return (
    <div
      ref={overlayRef}
      className={`pet-overlay ${drag ? 'dragging' : ''}`}
      style={{
        left: `${position.x}px`,
        top: `${position.y}px`,
        width: `${petWidth}px`,
        height: `${petHeight}px`,
        '--pet-bubble-offset-x': `${settings.bubble_offset_x ?? 12}px`,
        '--pet-bubble-offset-y': `${settings.bubble_offset_y ?? -12}px`,
      } as CSSProperties}
      onPointerDown={startDrag}
      onPointerEnter={startJump}
      aria-label={selectedPet.display_name || selectedPet.id}
      title={selectedPet.display_name || selectedPet.id}
    >
      {settings.show_status_bubble && bubbleText && !drag ? <div className="pet-status-bubble">{bubbleText}</div> : null}
      <PetSprite
        spritesheetUrl={spriteUrl}
        state={animationState}
        scale={scale}
        className="pet-sprite"
        onAnimationComplete={handleAnimationComplete}
      />
    </div>
  );
}

function normalizeSettings(value: Partial<PetSettings> | null | undefined): PetSettings {
  const settings = { ...DEFAULT_SETTINGS, ...(value || {}) };
  return {
    ...settings,
    pet_enabled: Boolean(settings.pet_enabled),
    default_pet_id: typeof settings.default_pet_id === 'string' ? settings.default_pet_id : '',
    pet_scale: clampNumber(Number(settings.pet_scale) || 1, 0.5, 2),
    show_status_bubble: Boolean(settings.show_status_bubble),
    bubble_offset_x: clampNumber(Number(settings.bubble_offset_x ?? 12), -240, 240),
    bubble_offset_y: clampNumber(Number(settings.bubble_offset_y ?? -12), -240, 240),
    jump_on_hover: Boolean(settings.jump_on_hover),
    running_prefix: typeof settings.running_prefix === 'string' ? settings.running_prefix : DEFAULT_SETTINGS.running_prefix,
    position: {
      mode: settings.position?.mode === 'custom' ? 'custom' : 'default',
      x: typeof settings.position?.x === 'number' ? settings.position.x : null,
      y: typeof settings.position?.y === 'number' ? settings.position.y : null,
    },
    bubble_texts: { ...DEFAULT_BUBBLE_TEXTS, ...(settings.bubble_texts || {}) },
  };
}

function resolveInitialPosition(settings: PetSettings, width: number, height: number): { x: number; y: number } {
  if (settings.position.mode === 'custom' && typeof settings.position.x === 'number' && typeof settings.position.y === 'number') {
    return clampPosition({ x: settings.position.x, y: settings.position.y }, width, height);
  }
  return defaultPosition(width, height);
}

function defaultPosition(width: number, height: number): { x: number; y: number } {
  return clampPosition(
    {
      x: window.innerWidth - width - DEFAULT_MARGIN_RIGHT,
      y: window.innerHeight - height - DEFAULT_MARGIN_BOTTOM,
    },
    width,
    height,
  );
}

function clampPosition(position: { x: number; y: number }, width: number, height: number): { x: number; y: number } {
  const margin = 8;
  return {
    x: clampNumber(position.x, margin, Math.max(margin, window.innerWidth - width - margin)),
    y: clampNumber(position.y, margin, Math.max(margin, window.innerHeight - height - margin)),
  };
}

function clampNumber(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function pickActiveRun(runs: Run[], sessionId?: string): Run | null {
  return [...runs]
    .filter((run) => run.session_id === sessionId && ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(run.status))
    .sort(compareRunsByRecent)[0] || null;
}

function pickLatestTerminalRun(runs: Run[], sessionId?: string): Run | null {
  const now = Date.now();
  return [...runs]
    .filter((run) => run.session_id === sessionId && ['DONE', 'FAILED', 'CANCELLED', 'INTERRUPTED'].includes(run.status))
    .filter((run) => now - runTimestamp(run) <= TERMINAL_HOLD_MS)
    .sort(compareRunsByRecent)[0] || null;
}

function compareRunsByRecent(a: Run, b: Run): number {
  return runTimestamp(b) - runTimestamp(a);
}

function runTimestamp(run: Run): number {
  const timestamp = Date.parse(run.updated_at || run.finished_at || run.created_at || '');
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function mapRunToPetState(run: Run | null): PetSpriteState {
  if (!run) return 'idle';
  if (run.status === 'WAITING_FOR_USER') return 'waiting';
  if (['PENDING', 'RUNNING', 'CANCELLING'].includes(run.status)) return 'running';
  if (run.status === 'DONE') return 'review';
  if (['FAILED', 'CANCELLED', 'INTERRUPTED'].includes(run.status)) return 'failed';
  return 'idle';
}

function pickRunningStep(steps: RunStep[]): RunStep | null {
  return [...steps]
    .filter((step) => step.status === 'running')
    .sort((a, b) => (b.order ?? 0) - (a.order ?? 0) || Date.parse(b.updated_at || b.created_at || '') - Date.parse(a.updated_at || a.created_at || ''))[0] || null;
}

function buildBubbleText(settings: PetSettings, activeRun: Run | null, terminalRun: Run | null, runningStep: RunStep | null): string {
  if (activeRun && ['PENDING', 'RUNNING', 'CANCELLING'].includes(activeRun.status)) {
    const task = runningTaskLabel(activeRun, runningStep);
    return `${settings.running_prefix || DEFAULT_SETTINGS.running_prefix}${task}`;
  }
  const texts = settings.bubble_texts;
  if (activeRun?.status === 'WAITING_FOR_USER') return texts.waiting || '';
  if (!terminalRun) return texts.idle || '';
  if (terminalRun.status === 'DONE') return texts.done || '';
  if (terminalRun.status === 'FAILED') return texts.failed || '';
  if (terminalRun.status === 'CANCELLED') return texts.cancelled || '';
  if (terminalRun.status === 'INTERRUPTED') return texts.interrupted || '';
  return '';
}

function runningTaskLabel(run: Run, step: RunStep | null): string {
  const label = step?.label || '';
  if (label && PET_RUN_STEP_TASK_LABELS[label]) return PET_RUN_STEP_TASK_LABELS[label];
  if (label) return label.slice(0, 16);
  if (run.status === 'PENDING') return '\u51c6\u5907\u4efb\u52a1';
  if (run.status === 'CANCELLING') return '\u53d6\u6d88\u4efb\u52a1';
  return '\u8fd0\u884c\u4efb\u52a1';
}
