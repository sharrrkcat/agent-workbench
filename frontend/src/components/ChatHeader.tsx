import { BookOpen, ChevronDown, DatabaseZap, Minus, MoreHorizontal, Plus, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import { AgentSwitcher } from './AgentSwitcher';
import { resolveCurrentLlmProfile, useWorkbenchStore } from '../store/useWorkbenchStore';
import { getModelProfileStatusLabel, getModelProfileStatusTitle } from '../i18n/formatters';
import { getModelProfileStatus, statusPillClass } from '../utils/modelStatus';
import { usePopoverPresence } from '../hooks/usePopoverPresence';
import type { ContextMode, GeneralSettings, KnowledgeBase, Message, RuntimeMemoryResultItem, RuntimeMemoryTarget, RuntimeMemoryTargetSummary, RuntimeResources, SessionKnowledgeBinding } from '../types';

export function ChatHeader({ onOpenSettings }: { onOpenSettings: () => void }) {
  const { t } = useTranslation();
  const state = useWorkbenchStore();
  const currentProfile = resolveCurrentLlmProfile(state);
  const modelStatus = getModelProfileStatus(currentProfile, state.llmProviderStatuses);
  const tokenSummary = useMemo(() => summarizeSessionTokens(state.messages), [state.messages]);
  const generalSettings = useWorkbenchStore((store) => store.generalSettings);
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const [sessionMenuOpen, setSessionMenuOpen] = useState(false);

  return (
    <header className="topbar">
      <div className="topbar-left">
        <AgentSwitcher />
      </div>
      <div className="topbar-actions">
        <ChatStatusPill summary={tokenSummary} settings={generalSettings} />
        <SessionKnowledgePicker
          open={knowledgeOpen}
          onOpenChange={(nextOpen) => {
            setKnowledgeOpen(nextOpen);
            if (nextOpen) setSessionMenuOpen(false);
          }}
          onOpenSettings={onOpenSettings}
        />
        <button
          className={`status-pill ${statusClass(modelStatus)}`}
          type="button"
          onClick={() => void state.refreshProviderStatuses()}
          title={statusTitle(modelStatus, currentProfile, t)}
        >
          <span />
          {getModelProfileStatusLabel(modelStatus.code, modelStatus.label, t)}
        </button>
        <SessionMenu
          open={sessionMenuOpen}
          onOpenChange={(nextOpen) => {
            setSessionMenuOpen(nextOpen);
            if (nextOpen) setKnowledgeOpen(false);
          }}
        />
      </div>
    </header>
  );
}

function ChatStatusPill({ summary, settings }: { summary: SessionTokenSummary; settings?: GeneralSettings }) {
  const { t } = useTranslation();
  const [resources, setResources] = useState<RuntimeResources | null>(null);
  const [resourceError, setResourceError] = useState('');
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const resourceEnabled = settings?.resource_status_panel_enabled ?? false;
  const showTokens = settings?.resource_status_show_tokens ?? true;
  const total = formatTokenAmount(summary.total, summary.estimated);
  const totalDetail = formatTokenCount(summary.total, summary.estimated);
  const input = formatTokenCount(summary.input, false);
  const output = formatTokenCount(summary.output, summary.estimated);
  const items = buildStatusItems(resources, settings, total, t);
  const visible = resourceEnabled || showTokens;
  const expandable = resourceEnabled;

  useEffect(() => {
    if (!resourceEnabled) {
      setResources(null);
      setResourceError('');
      setOpen(false);
      return;
    }
    let cancelled = false;
    let timeoutId = 0;

    async function load() {
      if (document.visibilityState === 'hidden') {
        timeoutId = window.setTimeout(load, 4000);
        return;
      }
      try {
        const nextResources = await api.getRuntimeResources();
        if (!cancelled) {
          setResources(nextResources);
          setResourceError('');
        }
      } catch (err) {
        if (!cancelled) setResourceError(err instanceof Error ? err.message : t('chat:resources.unavailable'));
      } finally {
        if (!cancelled) timeoutId = window.setTimeout(load, 4000);
      }
    }

    void load();
    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [resourceEnabled, t]);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!wrapRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false);
    }
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  if (!visible) return null;

  const label = items.length ? items.join(' · ') : t('chat:resources.loading');
  const tokenTooltip = t('chat:tokens.tooltip', {
    input,
    output,
    total: totalDetail,
  });
  const title = [label, tokenTooltip].filter(Boolean).join('\n');

  return (
    <div className="chat-status-wrap" ref={wrapRef}>
      <button
        className={`status-pill token-pill chat-status-pill ${expandable ? 'expandable' : ''}`}
        type="button"
        title={title}
        aria-label={t('chat:resources.statusPanel')}
        aria-expanded={open}
        onClick={() => {
          if (expandable) setOpen(!open);
        }}
      >
        <span className="chat-status-text">{label}</span>
        {expandable ? <ChevronDown size={13} className={`chat-status-chevron ${open ? 'open' : ''}`} /> : null}
      </button>
      <div className={`chat-status-panel ${open ? 'open' : ''}`} aria-hidden={!open}>
        <ChatStatusPanel resources={resources} resourceError={resourceError} settings={settings} summary={summary} />
      </div>
    </div>
  );
}

function ChatStatusPanel({
  resources,
  resourceError,
  settings,
  summary,
}: {
  resources: RuntimeResources | null;
  resourceError: string;
  settings?: GeneralSettings;
  summary: SessionTokenSummary;
}) {
  const { t } = useTranslation();
  const gpu = resources?.gpus.find((item) => item.available) || resources?.gpus[0];
  const rows: { label: string; value: string }[] = [];
  if (resources?.cpu.available) rows.push({ label: t('chat:resources.cpu'), value: formatPercent(resources.cpu.percent) });
  if (resources?.cpu && !resources.cpu.available && (settings?.resource_status_show_cpu ?? true)) {
    rows.push({ label: t('chat:resources.cpuUnavailable'), value: resourceUnavailableReason(resources.cpu.reason, 'cpu', t) });
  }
  if (resources?.memory.available) rows.push({ label: t('chat:resources.ram'), value: formatBytesPair(resources.memory.used_bytes, resources.memory.total_bytes, resources.memory.percent) });
  if (resources?.memory && !resources.memory.available && (settings?.resource_status_show_ram ?? true)) {
    rows.push({ label: t('chat:resources.ramUnavailable'), value: resourceUnavailableReason(resources.memory.reason, 'ram', t) });
  }
  if (gpu?.available) {
    rows.push({ label: t('chat:resources.gpu'), value: `${gpu.name || t('chat:resources.gpu')} · ${formatPercent(gpu.utilization_percent)}` });
    rows.push({ label: t('chat:resources.vram'), value: formatBytesPair(gpu.memory_used_bytes, gpu.memory_total_bytes, gpu.memory_percent) });
  } else if (gpu) {
    const reason = resourceUnavailableReason(gpu.reason, 'gpu', t);
    if (settings?.resource_status_show_gpu ?? true) rows.push({ label: t('chat:resources.gpuUnavailable'), value: reason });
    if (settings?.resource_status_show_vram ?? true) rows.push({ label: t('chat:resources.vramUnavailable'), value: reason });
  } else if (resources) {
    const reason = resourceUnavailableReason(resources.error, 'gpu', t);
    if (settings?.resource_status_show_gpu ?? true) rows.push({ label: t('chat:resources.gpuUnavailable'), value: reason });
    if (settings?.resource_status_show_vram ?? true) rows.push({ label: t('chat:resources.vramUnavailable'), value: reason });
  }
  if (resources?.process.backend_memory_bytes != null) {
    rows.push({ label: t('chat:resources.backendMemory'), value: formatBytes(resources.process.backend_memory_bytes) });
  }
  if (settings?.resource_status_show_tokens ?? true) {
    rows.push({ label: t('chat:resources.totalTokens'), value: formatTokenAmount(summary.total, summary.estimated) });
    rows.push({ label: t('chat:resources.inputTokens'), value: formatTokenAmount(summary.input, false) });
    rows.push({ label: t('chat:resources.outputTokens'), value: formatTokenAmount(summary.output, summary.estimated) });
  }
  if (resources?.updated_at) {
    rows.push({ label: t('chat:resources.updated'), value: formatDateTime(resources.updated_at) });
  }

  return (
    <div className="chat-status-panel-inner">
      <strong>{t('chat:resources.title')}</strong>
      {resourceError || resources?.error ? <p className="chat-status-panel-error">{t('chat:resources.unavailable')}</p> : null}
      {!resourceError && !resources ? <p className="chat-status-panel-muted">{t('chat:resources.loading')}</p> : null}
      {rows.length ? (
        <dl>
          {rows.map((row) => (
            <div key={row.label}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  );
}

function SessionMenu({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation();
  const currentSession = useWorkbenchStore((state) => state.currentSession);
  const deleteSession = useWorkbenchStore((state) => state.deleteSession);
  const updateSessionContextMode = useWorkbenchStore((state) => state.updateSessionContextMode);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const contextMode = currentSession?.context_mode === 'group_transcript' ? 'group_transcript' : 'single_assistant';
  const [memoryTargets, setMemoryTargets] = useState<RuntimeMemoryTargetSummary[]>([]);
  const [memoryBusy, setMemoryBusy] = useState(false);
  const [memoryFeedback, setMemoryFeedback] = useState('');
  const [memoryError, setMemoryError] = useState('');
  const menuRendered = usePopoverPresence(open);

  useEffect(() => {
    onOpenChange(false);
  }, [currentSession?.session_id]);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!menuRef.current?.contains(event.target as Node)) {
        onOpenChange(false);
      }
    }
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') onOpenChange(false);
    }
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [onOpenChange, open]);

  useEffect(() => {
    if (!open || !currentSession?.session_id) return;
    let cancelled = false;
    async function loadMemorySummary() {
      try {
        setMemoryError('');
        const summary = await api.getRuntimeMemory(currentSession!.session_id);
        if (!cancelled) setMemoryTargets(summary.targets);
      } catch (err) {
        if (!cancelled) setMemoryError(err instanceof Error ? err.message : t('chat:memory.loadFailed'));
      }
    }
    void loadMemorySummary();
    return () => {
      cancelled = true;
    };
  }, [currentSession?.session_id, open, t]);

  function confirmDelete() {
    if (!currentSession) return;
    const confirmed = window.confirm(t('chat:confirmDeleteSession'));
    if (!confirmed) return;
    onOpenChange(false);
    void deleteSession(currentSession.session_id);
  }

  function changeContextMode(nextMode: ContextMode) {
    if (!currentSession) return;
    void updateSessionContextMode(nextMode);
  }

  async function freeMemory(target: RuntimeMemoryTarget) {
    if (!currentSession || memoryBusy) return;
    setMemoryBusy(true);
    try {
      const result = await api.freeRuntimeMemory([target], currentSession.session_id);
      setMemoryFeedback(formatMemoryFeedback(result.results, t));
      const summary = await api.getRuntimeMemory(currentSession.session_id);
      setMemoryTargets(summary.targets);
      setMemoryError('');
    } catch (err) {
      setMemoryError(err instanceof Error ? err.message : t('chat:memory.freeFailed'));
    } finally {
      setMemoryBusy(false);
    }
  }

  const memoryByTarget = useMemo(() => new Map(memoryTargets.map((target) => [target.target, target])), [memoryTargets]);
  const hasFreeableTarget = memoryTargets.some((target) => isMemoryTargetEnabled(target));

  return (
    <div className="session-menu-wrap" ref={menuRef}>
      <button
        className="icon-button"
        type="button"
        disabled={!currentSession}
        title={t('chat:sessionOptions')}
        aria-label={t('chat:sessionOptions')}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => onOpenChange(!open)}
      >
        <MoreHorizontal size={18} />
      </button>
      {menuRendered ? (
        <div className={`session-menu popover-surface ${open ? '' : 'closing'}`} role="menu" aria-hidden={!open}>
          <div className="session-menu-mode" aria-label={t('chat:conversationMode')}>
            <span>{t('chat:mode')}</span>
            <div className="mode-switcher compact">
              <button
                type="button"
                className={contextMode === 'single_assistant' ? 'selected' : ''}
                onClick={() => changeContextMode('single_assistant')}
                title={t('chat:modeSingleTitle')}
              >
                {t('chat:modeSingle')}
              </button>
              <button
                type="button"
                className={contextMode === 'group_transcript' ? 'selected' : ''}
                onClick={() => changeContextMode('group_transcript')}
                title={t('chat:modeGroupTitle')}
              >
                {t('chat:modeGroup')}
              </button>
            </div>
          </div>
          <div className="session-menu-memory" aria-label={t('chat:memory.freeMemory')}>
            <span>{t('chat:memory.freeMemory')}</span>
            <MemoryMenuItem target="llm" summary={memoryByTarget.get('llm')} busy={memoryBusy} onFree={freeMemory} />
            <MemoryMenuItem target="comfyui" summary={memoryByTarget.get('comfyui')} busy={memoryBusy} onFree={freeMemory} />
            <MemoryMenuItem target="embedding" summary={memoryByTarget.get('embedding')} busy={memoryBusy} onFree={freeMemory} />
            <MemoryMenuItem target="reranker" summary={memoryByTarget.get('reranker')} busy={memoryBusy} onFree={freeMemory} />
            <button
              type="button"
              role="menuitem"
              className="session-menu-item"
              disabled={memoryBusy || !hasFreeableTarget}
              title={hasFreeableTarget ? t('chat:memory.freeAll') : t('chat:memory.noAvailableTargets')}
              onClick={() => void freeMemory('all')}
            >
              <DatabaseZap size={14} />
              <span>{t('chat:memory.freeAll')}</span>
            </button>
            {memoryFeedback ? <p className="session-menu-feedback">{memoryFeedback}</p> : null}
            {memoryError ? <p className="session-menu-error">{memoryError}</p> : null}
          </div>
          <button type="button" role="menuitem" className="session-menu-item danger" onClick={confirmDelete}>
            <Trash2 size={14} />
            <span>{t('chat:deleteSession', { name: '' }).trim()}</span>
          </button>
        </div>
      ) : null}
    </div>
  );
}

function MemoryMenuItem({
  target,
  summary,
  busy,
  onFree,
}: {
  target: Exclude<RuntimeMemoryTarget, 'all'>;
  summary?: RuntimeMemoryTargetSummary;
  busy: boolean;
  onFree: (target: RuntimeMemoryTarget) => Promise<void>;
}) {
  const { t } = useTranslation();
  const disabled = busy || !summary || !isMemoryTargetEnabled(summary);
  const reason = summary ? memoryReason(summary, t) : t('chat:memory.statusUnknown');
  return (
    <button
      type="button"
      role="menuitem"
      className="session-menu-item"
      disabled={disabled}
      title={disabled ? reason : memoryActionLabel(target, t)}
      onClick={() => void onFree(target)}
    >
      <DatabaseZap size={14} />
      <span>
        {memoryActionLabel(target, t)}
        {disabled && reason ? <small>{reason}</small> : null}
      </span>
    </button>
  );
}

function isMemoryTargetEnabled(summary: RuntimeMemoryTargetSummary): boolean {
  return summary.available && summary.enabled && summary.status !== 'busy' && summary.status !== 'unavailable';
}

function memoryActionLabel(target: RuntimeMemoryTarget, t: ReturnType<typeof useTranslation>['t']): string {
  const key = {
    llm: 'chat:memory.freeLlm',
    comfyui: 'chat:memory.freeComfyui',
    embedding: 'chat:memory.freeEmbedding',
    reranker: 'chat:memory.freeReranker',
    all: 'chat:memory.freeAll',
  }[target];
  return t(key);
}

function memoryReason(summary: RuntimeMemoryTargetSummary, t: ReturnType<typeof useTranslation>['t']): string {
  const reason = summary.reason || '';
  if (summary.status === 'busy') return t('chat:memory.busy');
  if (summary.status === 'not_loaded') return t('chat:memory.noModelLoaded');
  if (reason === 'Not connected.') return t('chat:memory.notConnected');
  if (reason === 'Current provider is not LM Studio.') return t('chat:memory.notLmStudio');
  if (reason === 'No model loaded.') return t('chat:memory.noModelLoaded');
  return reason || t('chat:memory.statusUnknown');
}

function formatMemoryFeedback(results: RuntimeMemoryResultItem[], t: ReturnType<typeof useTranslation>['t']): string {
  if (!results.length) return t('chat:memory.releaseResult');
  return [
    t('chat:memory.releaseResult'),
    ...results.map((item) => `${memoryTargetLabel(item.target, t)}: ${memoryStatusLabel(item.status, t)}${item.message ? ` - ${localizeMemoryMessage(item.message, t)}` : ''}`),
  ].join('\n');
}

function memoryTargetLabel(target: RuntimeMemoryResultItem['target'], t: ReturnType<typeof useTranslation>['t']): string {
  const key = {
    llm: 'chat:memory.llm',
    comfyui: 'chat:memory.comfyui',
    embedding: 'chat:memory.embedding',
    reranker: 'chat:memory.reranker',
  }[target];
  return t(key);
}

function memoryStatusLabel(status: string, t: ReturnType<typeof useTranslation>['t']): string {
  const key = {
    freed: 'chat:memory.freed',
    skipped: 'chat:memory.skipped',
    busy: 'chat:memory.busy',
    unavailable: 'chat:memory.unavailable',
    failed: 'chat:memory.failed',
  }[status];
  return key ? t(key) : status;
}

function localizeMemoryMessage(message: string, t: ReturnType<typeof useTranslation>['t']): string {
  if (message === 'Freed.') return t('chat:memory.freed');
  if (message === 'Not connected.') return t('chat:memory.notConnected');
  if (message === 'No model loaded.') return t('chat:memory.noModelLoaded');
  if (message === 'Current provider is not LM Studio.') return t('chat:memory.notLmStudio');
  if (message.toLowerCase().includes('busy')) return t('chat:memory.busy');
  return message;
}

function SessionKnowledgePicker({
  open,
  onOpenChange,
  onOpenSettings,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onOpenSettings: () => void;
}) {
  const { t } = useTranslation();
  const currentSession = useWorkbenchStore((state) => state.currentSession);
  const pickerRef = useRef<HTMLDivElement | null>(null);
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [bindings, setBindings] = useState<SessionKnowledgeBinding[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const selectedIds = useMemo(() => new Set(bindings.filter((binding) => binding.enabled).map((binding) => binding.knowledge_base_id)), [bindings]);
  const enabledBases = bases.filter((base) => selectedIds.has(base.id));
  const availableBases = bases.filter((base) => !selectedIds.has(base.id));
  const menuRendered = usePopoverPresence(open);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!pickerRef.current?.contains(event.target as Node)) {
        onOpenChange(false);
      }
    }
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') onOpenChange(false);
    }
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [onOpenChange, open]);

  useEffect(() => {
    if (!currentSession?.session_id) {
      setBases([]);
      setBindings([]);
      onOpenChange(false);
      return;
    }
    let cancelled = false;
    async function load() {
      try {
        setError('');
        const [nextBases, nextBindings] = await Promise.all([
          api.listKnowledgeBases(),
          api.listSessionKnowledgeBases(currentSession!.session_id),
        ]);
        if (cancelled) return;
        setBases(nextBases);
        setBindings(nextBindings);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : t('chat:loadKnowledgeBasesFailed'));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [currentSession?.session_id]);

  async function toggleBase(base: KnowledgeBase) {
    if (!currentSession || busy || !base.enabled) return;
    const nextIds = selectedIds.has(base.id)
      ? [...selectedIds].filter((id) => id !== base.id)
      : [...selectedIds, base.id];
    setBusy(true);
    try {
      const nextBindings = await api.updateSessionKnowledgeBases(currentSession.session_id, nextIds);
      setBindings(nextBindings);
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : t('chat:saveKnowledgeBasesFailed'));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="knowledge-picker" ref={pickerRef}>
      <button
        type="button"
        className="status-pill"
        disabled={!currentSession}
        onClick={() => onOpenChange(!open)}
        title={t('chat:selectKnowledgeBases')}
      >
        <BookOpen size={14} />
        KB: {selectedIds.size}
      </button>
      {menuRendered ? (
        <div className={`knowledge-picker-menu popover-surface ${open ? '' : 'closing'}`} aria-hidden={!open}>
          <div className="knowledge-picker-title">
            <strong>{t('chat:knowledge')}</strong>
            <span>{t('chat:selectedCount', { count: selectedIds.size })}</span>
          </div>
          {error ? <p className="settings-error-text">{error}</p> : null}
          {!bases.length ? (
            <div className="settings-empty-state compact">
              {t('chat:noKnowledgeBases')}
              <button type="button" className="settings-secondary-button" onClick={onOpenSettings} title={t('common:openSettings')}>{t('common:openSettings')}</button>
            </div>
          ) : null}
          {bases.length ? (
            <div className="knowledge-picker-sections">
              <KnowledgePickerSection
                title={t('chat:enabledKnowledgeBases')}
                empty={t('chat:noEnabledKnowledgeBases')}
                bases={enabledBases}
                busy={busy}
                action="remove"
                onToggle={toggleBase}
              />
              <KnowledgePickerSection
                title={t('chat:availableKnowledgeBases')}
                empty={t('chat:noAvailableKnowledgeBases')}
                bases={availableBases}
                busy={busy}
                action="add"
                onToggle={toggleBase}
              />
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function KnowledgePickerSection({
  title,
  empty,
  bases,
  busy,
  action,
  onToggle,
}: {
  title: string;
  empty: string;
  bases: KnowledgeBase[];
  busy: boolean;
  action: 'add' | 'remove';
  onToggle: (base: KnowledgeBase) => Promise<void>;
}) {
  const { t } = useTranslation();
  return (
    <section className="knowledge-picker-section">
      <h3>{title}</h3>
      {bases.length ? (
        <div className="knowledge-pill-list">
          {bases.map((base) => (
            <button
              key={base.id}
              type="button"
              className={`knowledge-pill ${action === 'remove' ? 'enabled' : 'available'} ${base.index_status === 'ready' ? '' : 'danger'} ${base.enabled ? '' : 'disabled'}`}
              disabled={busy || !base.enabled}
              onClick={() => void onToggle(base)}
              title={base.enabled ? t(action === 'add' ? 'chat:enableKnowledgeBase' : 'chat:disableKnowledgeBase', { name: base.name }) : t('chat:knowledgeBaseDisabled', { name: base.name })}
            >
              <span>
                <strong>{base.name}</strong>
              </span>
              {action === 'add' ? <Plus size={14} className="knowledge-pill-action" /> : <Minus size={14} className="knowledge-pill-action" />}
            </button>
          ))}
        </div>
      ) : (
        <p className="knowledge-picker-empty">{empty}</p>
      )}
    </section>
  );
}

function statusTitle(modelStatus: ReturnType<typeof getModelProfileStatus>, currentProfile: ReturnType<typeof resolveCurrentLlmProfile>, t: ReturnType<typeof useTranslation>['t']): string {
  return [
    currentProfile?.name || currentProfile?.alias || t('common:default'),
    t('chat:statusBar.requested', { model: currentProfile?.model_id || t('chat:statusBar.none') }),
    `Status: ${modelStatus.code}`,
    getModelProfileStatusTitle(modelStatus.code, modelStatus.title, t),
  ].filter(Boolean).join('\n');
}

function statusClass(modelStatus: ReturnType<typeof getModelProfileStatus>): string {
  return statusPillClass(modelStatus);
}

function resourceUnavailableReason(reason: string | null | undefined, kind: 'cpu' | 'ram' | 'gpu', t: ReturnType<typeof useTranslation>['t']): string {
  const normalized = (reason || '').trim().toLowerCase();
  if (normalized.includes('psutil')) return t('chat:resources.missingPsutilDependency');
  if (kind === 'gpu' && (!normalized || normalized.includes('nvml') || normalized.includes('pynvml'))) {
    return t('chat:resources.installNvmlDependency');
  }
  return reason?.trim() || t('chat:resources.notAvailable');
}

function buildStatusItems(resources: RuntimeResources | null, settings: GeneralSettings | undefined, total: string, t: ReturnType<typeof useTranslation>['t']): string[] {
  const resourceEnabled = settings?.resource_status_panel_enabled ?? false;
  const items: string[] = [];
  const gpu = resources?.gpus.find((item) => item.available);
  if (resourceEnabled && resources?.cpu.available && (settings?.resource_status_show_cpu ?? true)) {
    items.push(`${t('chat:resources.cpu')} ${formatPercent(resources.cpu.percent)}`);
  }
  if (resourceEnabled && resources?.memory.available && (settings?.resource_status_show_ram ?? true)) {
    const value = settings?.resource_status_ram_display_mode === 'value'
      ? formatByteValuePair(resources.memory.used_bytes, resources.memory.total_bytes)
      : formatPercent(resources.memory.percent);
    items.push(`${t('chat:resources.ram')} ${value}`);
  }
  if (resourceEnabled && gpu?.available && (settings?.resource_status_show_gpu ?? true)) {
    items.push(`${t('chat:resources.gpu')} ${formatPercent(gpu.utilization_percent)}`);
  }
  if (resourceEnabled && gpu?.available && (settings?.resource_status_show_vram ?? true)) {
    const value = settings?.resource_status_vram_display_mode === 'value'
      ? formatByteValuePair(gpu.memory_used_bytes, gpu.memory_total_bytes)
      : formatPercent(gpu.memory_percent);
    items.push(`${t('chat:resources.vram')} ${value}`);
  }
  if (settings?.resource_status_show_tokens ?? true) {
    items.push(t('chat:tokens.total', { count: total }));
  }
  return items;
}

function formatPercent(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
  return `${Math.round(value)}%`;
}

function formatBytesPair(used: number | null | undefined, total: number | null | undefined, percent: number | null | undefined): string {
  const value = formatByteValuePair(used, total);
  const pct = formatPercent(percent);
  return pct === '-' ? value : `${value} · ${pct}`;
}

function formatByteValuePair(used: number | null | undefined, total: number | null | undefined): string {
  if (typeof used !== 'number' || typeof total !== 'number' || !Number.isFinite(used) || !Number.isFinite(total) || total <= 0) {
    return '-';
  }
  return `${formatBytes(used)} / ${formatBytes(total)}`;
}

function formatBytes(value: number): string {
  if (value < 1024) return `${Math.round(value)} B`;
  if (value < 1024 * 1024) return `${trimTrailingZero((value / 1024).toFixed(1))} KB`;
  if (value < 1024 * 1024 * 1024) return `${trimTrailingZero((value / (1024 * 1024)).toFixed(1))} MB`;
  return `${trimTrailingZero((value / (1024 * 1024 * 1024)).toFixed(1))} GB`;
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString();
}

type SessionTokenSummary = {
  input: number;
  output: number;
  total: number;
  estimated: boolean;
};

function summarizeSessionTokens(messages: Message[]): SessionTokenSummary {
  return messages.reduce<SessionTokenSummary>(
    (summary, message) => {
      if (message.role !== 'assistant' && message.role !== 'agent') return summary;
      const metrics = plainRecord(message.metadata?.llm_metrics);
      if (!metrics) return summary;
      const input = numberValue(metrics.prompt_tokens) ?? numberValue(metrics.input_tokens) ?? 0;
      const providerOutput = numberValue(metrics.completion_tokens) ?? numberValue(metrics.output_tokens);
      const estimatedOutput = numberValue(metrics.estimated_completion_tokens);
      const output = providerOutput ?? estimatedOutput ?? 0;
      const estimated = metrics.usage_source === 'estimated' || (providerOutput === undefined && estimatedOutput !== undefined);
      return {
        input: summary.input + input,
        output: summary.output + output,
        total: summary.total + input + output,
        estimated: summary.estimated || estimated,
      };
    },
    { input: 0, output: 0, total: 0, estimated: false },
  );
}

function formatTokenCount(value: number, estimated: boolean): string {
  return `${formatTokenAmount(value, estimated)} tokens`;
}

function formatTokenAmount(value: number, estimated: boolean): string {
  const rounded = Math.max(0, Math.round(value));
  const prefix = estimated && rounded > 0 ? '~' : '';
  return `${prefix}${formatCompactNumber(rounded)}`;
}

function formatCompactNumber(value: number): string {
  if (value < 1000) return String(value);
  if (value < 1_000_000) return `${trimTrailingZero((value / 1000).toFixed(1))}k`;
  return `${trimTrailingZero((value / 1_000_000).toFixed(1))}M`;
}

function trimTrailingZero(value: string): string {
  return value.replace(/\.0$/, '');
}

function numberValue(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  return undefined;
}

function plainRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}
