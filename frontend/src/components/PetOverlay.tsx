import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react';
import { API_BASE_URL, api, joinApiUrl } from '../api/client';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { Message, PetBubbleTexts, PetCommandTexts, PetItem, PetSettings, Run, RunStep } from '../types';
import { PetSprite, type PetSpriteState } from './PetSprite';

type DragState = {
  pointerId: number;
  startPointerX: number;
  startPointerY: number;
  startX: number;
  startY: number;
  lastX: number;
};

type PetPosition = { x: number; y: number };
type PetCommandFeedback =
  | { type: 'wake'; animation: 'waving'; bubbleKey: 'wake' }
  | { type: 'tuck'; animation: 'waving'; bubbleKey: 'tuck'; hideAfterComplete: true }
  | { type: 'select'; animation: 'waving'; bubbleKey: 'select' }
  | null;
type ComposerWaitPhase = 'waiting' | 'idle';

const BASE_WIDTH = 192;
const BASE_HEIGHT = 208;
const DEFAULT_MARGIN_RIGHT = 28;
const DEFAULT_MARGIN_BOTTOM = 92;
const TERMINAL_HOLD_MS = 4200;
const PET_REFRESH_MS = 6000;
const PET_COMMAND_FRESH_MS = 10000;
const DEFAULT_PET_SCALE = 0.5;

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

const DEFAULT_COMMAND_TEXTS: PetCommandTexts = {
  wake: '\u5df2\u5524\u9192 {pet.display_name}',
  tuck: '{pet.display_name} \u5df2\u6682\u79bb',
  select: '\u5df2\u5207\u6362\u4e3a {pet.display_name}\u3002\n{pet.description}',
  status: '\u5f53\u524d pet\uff1a{pet.display_name}',
  reload: '\u5df2\u91cd\u65b0\u626b\u63cf pet\uff1a{valid_count} \u4e2a\u53ef\u7528\uff0c{invalid_count} \u4e2a\u65e0\u6548',
  no_pet: '\u8fd8\u6ca1\u6709\u53ef\u7528\u7684 pet',
  select_missing: '\u672a\u627e\u5230\u53ef\u7528 pet\uff1a{pet_id}',
};

const DEFAULT_SETTINGS: PetSettings = {
  pet_enabled: true,
  default_pet_id: '',
  pet_scale: DEFAULT_PET_SCALE,
  show_status_bubble: true,
  bubble_offset_x: 12,
  bubble_offset_y: -12,
  jump_on_hover: true,
  running_prefix: '\u6b63\u5728',
  position: { mode: 'default', x: null, y: null },
  bubble_texts: DEFAULT_BUBBLE_TEXTS,
  command_texts: DEFAULT_COMMAND_TEXTS,
};

export function PetOverlay() {
  const { currentSession, runs, stepsByRunId, messages, composerDraftText } = useWorkbenchStore();
  const [settings, setSettings] = useState<PetSettings | null>(null);
  const [pets, setPets] = useState<PetItem[]>([]);
  const [localPosition, setLocalPosition] = useState<PetPosition | null>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const [dragDirection, setDragDirection] = useState<'left' | 'right'>('right');
  const [jumping, setJumping] = useState(false);
  const [hoverActive, setHoverActive] = useState(false);
  const [runningTask, setRunningTask] = useState<{ key: string; label: string } | null>(null);
  const [commandFeedback, setCommandFeedback] = useState<PetCommandFeedback>(null);
  const [composerWaitPhase, setComposerWaitPhase] = useState<ComposerWaitPhase>('waiting');
  const [terminalRun, setTerminalRun] = useState<Run | null>(null);
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const lastHeldTerminalRunIdRef = useRef<string | null>(null);
  const pendingSavedPositionRef = useRef<PetPosition | null>(null);
  const appliedSettingsPositionKeyRef = useRef('');
  const lastTaskKeyRef = useRef('');
  const previousPetEnabledRef = useRef<boolean | null>(null);
  const initialSettingsLoadedRef = useRef(false);
  const lastPetCommandMessageIdRef = useRef('');

  const validPets = useMemo(() => pets.filter((pet) => pet.valid && pet.spritesheet_url), [pets]);
  const selectedPet = useMemo(() => {
    if (!validPets.length || !settings) return null;
    return validPets.find((pet) => pet.id === settings.default_pet_id) || validPets[0];
  }, [settings, validPets]);

  const scale = clampNumber(settings?.pet_scale || DEFAULT_PET_SCALE, 0.5, 2);
  const petWidth = BASE_WIDTH * scale;
  const petHeight = BASE_HEIGHT * scale;
  const activeRun = useMemo(() => pickActiveRun(runs, currentSession?.session_id), [runs, currentSession?.session_id]);
  const runningStep = useMemo(() => (activeRun ? pickRunningStep(stepsByRunId[activeRun.run_id] || activeRun.steps || []) : null), [activeRun, stepsByRunId]);
  const runningTaskLabelValue = useMemo(() => (activeRun ? runningTaskLabel(activeRun, runningStep) : ''), [activeRun, runningStep]);
  const taskKey = useMemo(() => buildTaskKey(activeRun, runningStep), [activeRun, runningStep]);
  const hasComposerText = composerDraftText.trim().length > 0;
  const terminalState = useMemo(() => mapTerminalRunToPetState(terminalRun), [terminalRun]);
  const baseState: PetSpriteState = hasComposerText ? composerWaitPhase : terminalState;
  const animationState: PetSpriteState = drag
    ? dragDirection === 'left'
      ? 'running-left'
      : 'running-right'
    : commandFeedback
      ? commandFeedback.animation
      : jumping
      ? 'jumping'
      : runningTask
        ? 'running'
      : baseState;
  const bubbleText = settings ? buildBubbleText(settings, terminalRun, runningTask, commandFeedback) : '';
  const spriteUrl = selectedPet?.spritesheet_url ? joinApiUrl(API_BASE_URL, selectedPet.spritesheet_url) : '';

  const refreshPetState = useCallback(async (cancelled: () => boolean = () => false) => {
    try {
      const [settingsResponse, petsResponse] = await Promise.all([api.getPetSettings(), api.listPets()]);
      if (cancelled()) return;
      const nextSettings = normalizeSettings(settingsResponse.settings);
      const previousEnabled = previousPetEnabledRef.current;
      if (initialSettingsLoadedRef.current && previousEnabled === true && !nextSettings.pet_enabled) {
        setCommandFeedback({ type: 'tuck', animation: 'waving', bubbleKey: 'tuck', hideAfterComplete: true });
      }
      previousPetEnabledRef.current = nextSettings.pet_enabled;
      initialSettingsLoadedRef.current = true;
      setSettings(nextSettings);
      setPets(petsResponse.pets);
      setLocalPosition((current) => current || resolveInitialPosition(nextSettings, BASE_WIDTH * nextSettings.pet_scale, BASE_HEIGHT * nextSettings.pet_scale));
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
    const pendingPosition = pendingSavedPositionRef.current;
    if (pendingPosition) {
      if (settings.position.mode === 'custom' && positionsMatch(settings.position, pendingPosition)) {
        pendingSavedPositionRef.current = null;
        appliedSettingsPositionKeyRef.current = settingsPositionKey(settings);
      }
      return;
    }

    const nextSettingsPositionKey = settingsPositionKey(settings);
    const shouldApplySettingsPosition = nextSettingsPositionKey !== appliedSettingsPositionKeyRef.current;
    setLocalPosition((current) => {
      if (!current || shouldApplySettingsPosition) {
        appliedSettingsPositionKeyRef.current = nextSettingsPositionKey;
        return resolveInitialPosition(settings, petWidth, petHeight);
      }
      return clampPosition(current, petWidth, petHeight);
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
    if (!taskKey || !activeRun || !['PENDING', 'RUNNING', 'CANCELLING'].includes(activeRun.status)) return;
    if (lastTaskKeyRef.current === taskKey) return;
    lastTaskKeyRef.current = taskKey;
    setRunningTask({ key: taskKey, label: runningTaskLabelValue });
  }, [activeRun, runningTaskLabelValue, taskKey]);

  useEffect(() => {
    if (hasComposerText) return;
    setComposerWaitPhase('waiting');
  }, [hasComposerText]);

  useEffect(() => {
    const latestPetCommand = pickLatestPetCommandFeedback(messages);
    if (!latestPetCommand || latestPetCommand.messageId === lastPetCommandMessageIdRef.current) return;
    lastPetCommandMessageIdRef.current = latestPetCommand.messageId;
    setTerminalRun(null);
    setCommandFeedback(commandFeedbackForAction(latestPetCommand.action));
    void refreshPetState();
  }, [messages, refreshPetState]);

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
      setLocalPosition(next);
    };
    const onPointerUp = (event: PointerEvent) => {
      if (event.pointerId !== drag.pointerId) return;
      const finalPosition = clampPosition(
        {
          x: drag.startX + event.clientX - drag.startPointerX,
          y: drag.startY + event.clientY - drag.startPointerY,
        },
        petWidth,
        petHeight,
      );
      const savedPosition = { x: Math.round(finalPosition.x), y: Math.round(finalPosition.y) };
      pendingSavedPositionRef.current = savedPosition;
      setDrag(null);
      setLocalPosition(finalPosition);
      void api.updatePetSettings({ position: { mode: 'custom', ...savedPosition } }).then((response) => {
        setSettings(normalizeSettings(response.settings));
      }).catch(() => {
        pendingSavedPositionRef.current = null;
      });
    };
    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    window.addEventListener('pointercancel', onPointerUp);
    return () => {
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
      window.removeEventListener('pointercancel', onPointerUp);
    };
  }, [drag, petHeight, petWidth]);

  useEffect(() => {
    const onResize = () => {
      setLocalPosition((current) => clampPosition(current || defaultPosition(petWidth, petHeight), petWidth, petHeight));
    };
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [petHeight, petWidth]);

  const startJump = useCallback(() => {
    if (!settings?.jump_on_hover || drag) return;
    setHoverActive(true);
    setJumping(true);
  }, [drag, settings?.jump_on_hover]);

  const stopJump = useCallback(() => {
    if (drag) return;
    setHoverActive(false);
    setJumping(false);
  }, [drag]);

  const handlePlaybackComplete = useCallback((state: PetSpriteState) => {
    if (state === 'jumping' && !hoverActive) {
      setJumping(false);
    }
    if (state === 'jumping' && hoverActive) {
      setJumping(false);
    }
    if (state === 'running') {
      setRunningTask(null);
    }
    if (state === 'waving' && commandFeedback) {
      setCommandFeedback(null);
    }
    if ((state === 'waiting' || state === 'idle') && hasComposerText && !runningTask && !jumping && !drag && !commandFeedback) {
      setComposerWaitPhase((phase) => (phase === 'waiting' ? 'idle' : 'waiting'));
    }
  }, [commandFeedback, drag, hasComposerText, hoverActive, jumping, runningTask]);

  const repeatCount = useMemo(() => {
    if (animationState === 'jumping') return 3;
    if (animationState === 'running' && runningTask) return 2;
    if ((animationState === 'waiting' || animationState === 'idle') && hasComposerText) return 1;
    if (animationState === 'waving' && commandFeedback) return 1;
    return undefined;
  }, [animationState, commandFeedback, hasComposerText, runningTask]);

  const shouldRender = Boolean(
    selectedPet
    && spriteUrl
    && localPosition
    && (settings?.pet_enabled || Boolean(commandFeedback)),
  );

  const showBubble = settings?.show_status_bubble && bubbleText && !drag;

  const onPointerLeave = useCallback(() => {
    stopJump();
  }, [stopJump]);

  const onPointerEnter = useCallback(() => {
    startJump();
  }, [startJump]);

  function startDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || !localPosition) return;
    event.preventDefault();
    overlayRef.current?.setPointerCapture(event.pointerId);
    setHoverActive(false);
    setJumping(false);
    setDrag({
      pointerId: event.pointerId,
      startPointerX: event.clientX,
      startPointerY: event.clientY,
      startX: localPosition.x,
      startY: localPosition.y,
      lastX: event.clientX,
    });
  }

  if (!shouldRender) return null;

  const renderPosition = localPosition;
  const renderPet = selectedPet;
  if (!renderPosition || !renderPet) return null;

  return (
    <div
      ref={overlayRef}
      className={`pet-overlay ${drag ? 'dragging' : ''}`}
      style={{
        left: `${renderPosition.x}px`,
        top: `${renderPosition.y}px`,
        width: `${petWidth}px`,
        height: `${petHeight}px`,
        '--pet-bubble-offset-x': `${settings?.bubble_offset_x ?? 12}px`,
        '--pet-bubble-offset-y': `${settings?.bubble_offset_y ?? -12}px`,
      } as CSSProperties}
      onPointerDown={startDrag}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
      aria-label={renderPet.display_name || renderPet.id}
      title={renderPet.display_name || renderPet.id}
    >
      {showBubble ? <div className="pet-status-bubble">{bubbleText}</div> : null}
      <PetSprite
        spritesheetUrl={spriteUrl}
        state={animationState}
        scale={scale}
        className="pet-sprite"
        repeatCount={repeatCount}
        onPlaybackComplete={handlePlaybackComplete}
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
    pet_scale: clampNumber(Number(settings.pet_scale) || DEFAULT_PET_SCALE, 0.5, 2),
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
    command_texts: { ...DEFAULT_COMMAND_TEXTS, ...(settings.command_texts || {}) },
  };
}

function resolveInitialPosition(settings: PetSettings, width: number, height: number): { x: number; y: number } {
  if (settings.position.mode === 'custom' && typeof settings.position.x === 'number' && typeof settings.position.y === 'number') {
    return clampPosition({ x: settings.position.x, y: settings.position.y }, width, height);
  }
  return defaultPosition(width, height);
}

function settingsPositionKey(settings: PetSettings): string {
  if (settings.position.mode === 'custom' && typeof settings.position.x === 'number' && typeof settings.position.y === 'number') {
    return `custom:${Math.round(settings.position.x)}:${Math.round(settings.position.y)}`;
  }
  return 'default';
}

function positionsMatch(settingsPosition: PetSettings['position'], position: PetPosition): boolean {
  return (
    typeof settingsPosition.x === 'number'
    && typeof settingsPosition.y === 'number'
    && Math.round(settingsPosition.x) === Math.round(position.x)
    && Math.round(settingsPosition.y) === Math.round(position.y)
  );
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
    .filter((run) => run.kind !== 'command' || run.target_id !== '/pet')
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

function mapTerminalRunToPetState(run: Run | null): PetSpriteState {
  if (!run) return 'idle';
  if (run.status === 'DONE') return 'review';
  if (['FAILED', 'CANCELLED', 'INTERRUPTED'].includes(run.status)) return 'failed';
  return 'idle';
}

function buildTaskKey(run: Run | null, step: RunStep | null): string {
  if (!run || !['PENDING', 'RUNNING', 'CANCELLING'].includes(run.status)) return '';
  if (step) {
    return [
      run.run_id,
      step.step_id,
      step.updated_at || step.status || '',
      step.message || '',
      step.label || '',
    ].join(':');
  }
  return [
    run.run_id,
    run.status || '',
    run.current_step || run.stage || '',
    run.progress_message || '',
  ].join(':');
}

function pickRunningStep(steps: RunStep[]): RunStep | null {
  return [...steps]
    .filter((step) => step.status === 'running')
    .sort((a, b) => (b.order ?? 0) - (a.order ?? 0) || Date.parse(b.updated_at || b.created_at || '') - Date.parse(a.updated_at || a.created_at || ''))[0] || null;
}

function buildBubbleText(
  settings: PetSettings,
  terminalRun: Run | null,
  runningTask: { key: string; label: string } | null,
  commandFeedback: PetCommandFeedback,
): string {
  if (commandFeedback) return settings.bubble_texts[commandFeedback.bubbleKey] || '';
  if (runningTask) {
    return `${settings.running_prefix || DEFAULT_SETTINGS.running_prefix}${runningTask.label}`;
  }
  const texts = settings.bubble_texts;
  if (!terminalRun) return texts.idle || '';
  if (terminalRun.status === 'DONE') return texts.done || '';
  if (terminalRun.status === 'FAILED') return texts.failed || '';
  if (terminalRun.status === 'CANCELLED') return texts.cancelled || '';
  if (terminalRun.status === 'INTERRUPTED') return texts.interrupted || '';
  return '';
}

function commandFeedbackForAction(action: 'wake' | 'tuck' | 'select'): NonNullable<PetCommandFeedback> {
  if (action === 'tuck') return { type: 'tuck', animation: 'waving', bubbleKey: 'tuck', hideAfterComplete: true };
  if (action === 'select') return { type: 'select', animation: 'waving', bubbleKey: 'select' };
  return { type: 'wake', animation: 'waving', bubbleKey: 'wake' };
}

function pickLatestPetCommandFeedback(messages: Message[]): { messageId: string; action: 'wake' | 'tuck' | 'select' } | null {
  const messagesById = new Map(messages.map((message) => [message.message_id, message]));
  const now = Date.now();
  for (const message of [...messages].reverse()) {
    const parsed = parsePetCommandMessage(message, messagesById);
    if (!parsed) continue;
    if (now - messageTimestamp(message) > PET_COMMAND_FRESH_MS) return null;
    return parsed;
  }
  return null;
}

function parsePetCommandMessage(message: Message, messagesById: Map<string, Message>): { messageId: string; action: 'wake' | 'tuck' | 'select' } | null {
  if (message.metadata?.command === '/pet') {
    if (message.metadata.success === false) return null;
    const parentId = typeof message.metadata.parent_message_id === 'string' ? message.metadata.parent_message_id : message.parent_message_id || '';
    const parent = parentId ? messagesById.get(parentId) : null;
    const parentAction = parent ? parsePetCommandText(parent.content) : null;
    return parentAction ? { messageId: message.message_id, action: parentAction } : null;
  }
  if (message.role !== 'user') return null;
  const action = parsePetCommandText(message.content);
  if (action === 'select') return null;
  return action ? { messageId: message.message_id, action } : null;
}

function parsePetCommandText(content: unknown): 'wake' | 'tuck' | 'select' | null {
  if (typeof content !== 'string') return null;
  const match = content.trim().match(/^\/pet(?:\s+(\S+))?/i);
  if (!match) return null;
  const action = (match[1] || 'status').toLowerCase();
  return action === 'wake' || action === 'tuck' || action === 'select' ? action : null;
}

function messageTimestamp(message: Message): number {
  const timestamp = Date.parse(message.created_at || '');
  return Number.isFinite(timestamp) ? timestamp : Date.now();
}

function runningTaskLabel(run: Run, step: RunStep | null): string {
  const label = step?.label || '';
  if (label && PET_RUN_STEP_TASK_LABELS[label]) return PET_RUN_STEP_TASK_LABELS[label];
  if (label) return label.slice(0, 16);
  if (run.status === 'PENDING') return '\u51c6\u5907\u4efb\u52a1';
  if (run.status === 'CANCELLING') return '\u53d6\u6d88\u4efb\u52a1';
  return '\u8fd0\u884c\u4efb\u52a1';
}
