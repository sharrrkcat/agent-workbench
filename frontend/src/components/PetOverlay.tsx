import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react';
import { API_BASE_URL, api, joinApiUrl } from '../api/client';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { PetBubbleTexts, PetItem, PetSettings, Run, RunStep } from '../types';
import { PetSprite, type PetSpriteState } from './PetSprite';

const WIDTH = 192;
const HEIGHT = 208;
const DEFAULT_SETTINGS: PetSettings = {
  pet_enabled: true, default_pet_id: '', pet_scale: 0.5, show_status_bubble: true,
  bubble_offset_x: 12, bubble_offset_y: -12, jump_on_hover: true, running_prefix: '正在',
  position: { mode: 'default', x: null, y: null },
  bubble_texts: {
    idle: '', waiting: '等待确认', done: '完成啦', failed: '出错了', cancelled: '已取消', interrupted: '已中断',
    wake: '我来啦', tuck: '先睡一会儿', status: '我在这里', select: '换好啦', reload: '重新扫描完成',
    no_pet: '还没有可用的宠物', import_success: '导入成功', import_failed: '导入失败', delete_success: '已删除', delete_failed: '删除失败',
  },
};

type Drag = { id: number; px: number; py: number; x: number; y: number };

export function PetOverlay() {
  const [settings, setSettings] = useState<PetSettings>(DEFAULT_SETTINGS);
  const [pets, setPets] = useState<PetItem[]>([]);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [drag, setDrag] = useState<Drag | null>(null);
  const [hover, setHover] = useState(false);
  const [jumping, setJumping] = useState(false);
  const initialized = useRef(false);
  const session = useWorkbenchStore((state) => state.currentSession);
  const runs = useWorkbenchStore((state) => state.runs);
  const stepsByRunId = useWorkbenchStore((state) => state.stepsByRunId);
  const scale = clamp(settings.pet_scale, 0.5, 2);
  const width = WIDTH * scale;
  const height = HEIGHT * scale;

  const refresh = useCallback(async () => {
    try {
      const [settingResponse, petResponse] = await Promise.all([api.getPetSettings(), api.listPets()]);
      const next = normalize(settingResponse.settings);
      setSettings(next);
      setPets(petResponse.pets || []);
      if (!initialized.current) { setPosition(initialPosition(next, width, height)); initialized.current = true; }
    } catch { /* pets are optional */ }
  }, [height, width]);

  useEffect(() => { void refresh(); const listener = () => void refresh(); window.addEventListener('pet-settings-changed', listener); return () => window.removeEventListener('pet-settings-changed', listener); }, [refresh]);
  useEffect(() => { if (!settings.position || drag) return; setPosition((current) => settings.position.mode === 'custom' && settings.position.x != null && settings.position.y != null ? clampPosition({ x: settings.position.x, y: settings.position.y }, width, height) : clampPosition(current, width, height)); }, [settings.position, width, height, drag]);
  useEffect(() => { const onResize = () => setPosition((current) => clampPosition(current, width, height)); window.addEventListener('resize', onResize); return () => window.removeEventListener('resize', onResize); }, [width, height]);
  useEffect(() => { if (!drag) return; const move = (event: PointerEvent) => { if (event.pointerId !== drag.id) return; setPosition(clampPosition({ x: drag.x + event.clientX - drag.px, y: drag.y + event.clientY - drag.py }, width, height)); }; const up = (event: PointerEvent) => { if (event.pointerId !== drag.id) return; const next = clampPosition({ x: drag.x + event.clientX - drag.px, y: drag.y + event.clientY - drag.py }, width, height); setPosition(next); setDrag(null); void api.updatePetSettings({ position: { mode: 'custom', x: Math.round(next.x), y: Math.round(next.y) } }).then(() => window.dispatchEvent(new Event('pet-settings-changed'))).catch(() => undefined); }; window.addEventListener('pointermove', move); window.addEventListener('pointerup', up); window.addEventListener('pointercancel', up); return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); window.removeEventListener('pointercancel', up); }; }, [drag, width, height]);

  const pet = useMemo(() => { const valid = pets.filter((item) => item.valid && item.spritesheet_url); return valid.find((item) => item.id === settings.default_pet_id) || valid[0] || null; }, [pets, settings.default_pet_id]);
  const current = useMemo(() => currentRun(runs, session?.session_id), [runs, session?.session_id]);
  const step = current ? ((stepsByRunId[current.run_id] || current.steps || []).find((item) => item.status === 'running') || null) : null;
  const spriteState = stateFor(current, step, hover, jumping);
  const bubble = bubbleFor(settings, current, step);
  if (!settings.pet_enabled || !pet?.spritesheet_url) return null;

  function startDrag(event: ReactPointerEvent<HTMLDivElement>) { if (event.button !== 0) return; event.preventDefault(); setDrag({ id: event.pointerId, px: event.clientX, py: event.clientY, x: position.x, y: position.y }); setHover(false); setJumping(false); }
  return <div className="pet-overlay" style={{ left: position.x, top: position.y, width, height, '--pet-bubble-offset-x': `${settings.bubble_offset_x}px`, '--pet-bubble-offset-y': `${settings.bubble_offset_y}px` } as CSSProperties} onPointerDown={startDrag} onPointerEnter={() => { setHover(true); if (settings.jump_on_hover) setJumping(true); }} onPointerLeave={() => { setHover(false); setJumping(false); }} aria-label={pet.display_name}>
    {settings.show_status_bubble && bubble && !drag ? <div className="pet-status-bubble">{bubble}</div> : null}
    <PetSprite spritesheetUrl={joinApiUrl(API_BASE_URL, pet.spritesheet_url)} state={spriteState} scale={scale} className="pet-sprite" repeatCount={spriteState === 'jumping' ? 1 : undefined} onPlaybackComplete={() => setJumping(false)} />
  </div>;
}

function normalize(value: Partial<PetSettings>): PetSettings { return { ...DEFAULT_SETTINGS, ...value, position: { ...DEFAULT_SETTINGS.position, ...(value.position || {}) }, bubble_texts: { ...DEFAULT_SETTINGS.bubble_texts, ...(value.bubble_texts || {}) }, pet_scale: clamp(Number(value.pet_scale) || 0.5, 0.5, 2) }; }
function initialPosition(settings: PetSettings, width: number, height: number) { return settings.position.mode === 'custom' && settings.position.x != null && settings.position.y != null ? clampPosition({ x: settings.position.x, y: settings.position.y }, width, height) : clampPosition({ x: window.innerWidth - width - 28, y: window.innerHeight - height - 92 }, width, height); }
function clampPosition(value: { x: number; y: number }, width: number, height: number) { return { x: clamp(value.x || 0, 8, Math.max(8, window.innerWidth - width - 8)), y: clamp(value.y || 0, 8, Math.max(8, window.innerHeight - height - 8)) }; }
function clamp(value: number, min: number, max: number) { return Math.min(max, Math.max(min, value)); }
function currentRun(runs: Run[], sessionId?: string): Run | null { return [...runs].filter((run) => run.session_id === sessionId).sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)).find((run) => ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(run.status)) || [...runs].filter((run) => run.session_id === sessionId && ['DONE', 'FAILED', 'CANCELLED', 'INTERRUPTED'].includes(run.status)).sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at))[0] || null; }
function stateFor(run: Run | null, step: RunStep | null, hover: boolean, jumping: boolean): PetSpriteState { if (jumping) return 'jumping'; if (hover) return 'idle'; if (!run) return 'idle'; if (run.status === 'WAITING_FOR_USER') return 'waiting'; if (['PENDING', 'RUNNING', 'CANCELLING'].includes(run.status)) return step?.kind === 'approval' ? 'waiting' : 'running'; if (run.status === 'DONE') return 'review'; if (['FAILED', 'CANCELLED', 'INTERRUPTED'].includes(run.status)) return 'failed'; return 'idle'; }
function bubbleFor(settings: PetSettings, run: Run | null, step: RunStep | null): string { if (!run) return settings.bubble_texts.idle; if (run.status === 'WAITING_FOR_USER' || step?.kind === 'approval') return settings.bubble_texts.waiting; if (['PENDING', 'RUNNING', 'CANCELLING'].includes(run.status)) return `${settings.running_prefix}${step ? ` ${step.kind}` : ''}`; if (run.status === 'DONE') return settings.bubble_texts.done; if (run.status === 'FAILED') return settings.bubble_texts.failed; if (run.status === 'CANCELLED') return settings.bubble_texts.cancelled; if (run.status === 'INTERRUPTED') return settings.bubble_texts.interrupted; return settings.bubble_texts.status; }
