import { BookOpen, BookOpenText, ChevronDown, DatabaseZap, GripVertical, Layers, Minus, MoreHorizontal, Plus, Trash2, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import { AgentSwitcher } from './AgentSwitcher';
import { resolveCurrentLlmProfile, useWorkbenchStore } from '../store/useWorkbenchStore';
import { getModelProfileStatusLabel, getModelProfileStatusTitle } from '../i18n/formatters';
import { getModelProfileStatus, statusPillClass } from '../utils/modelStatus';
import { usePopoverPresence } from '../hooks/usePopoverPresence';
import type { ContextMode, GeneralSettings, KnowledgeBase, Message, RuntimeMemoryResultItem, RuntimeMemoryTarget, RuntimeMemoryTargetSummary, RuntimeResources, SessionKnowledgeBinding, SessionWorldbookBinding, Worldbook } from '../types';

export function ChatHeader({ onOpenSettings }: { onOpenSettings: () => void }) {
  const { t } = useTranslation();
  const state = useWorkbenchStore();
  const currentProfile = resolveCurrentLlmProfile(state);
  const modelStatus = getModelProfileStatus(currentProfile, state.llmProviderStatuses);
  const tokenSummary = useMemo(() => summarizeSessionTokens(state.messages), [state.messages]);
  const generalSettings = useWorkbenchStore((store) => store.generalSettings);
  const [contextSourcesOpen, setContextSourcesOpen] = useState(false);
  const [sessionMenuOpen, setSessionMenuOpen] = useState(false);

  return (
    <header className="topbar">
      <div className="topbar-left">
        <AgentSwitcher />
      </div>
      <div className="topbar-actions">
        <ChatStatusPill summary={tokenSummary} settings={generalSettings} />
        <ContextSourcesButton
          open={contextSourcesOpen}
          onOpenChange={(nextOpen) => {
            setContextSourcesOpen(nextOpen);
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
            if (nextOpen) setContextSourcesOpen(false);
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

function ContextSourcesButton({
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
  const [summary, setSummary] = useState<ContextSourcesSummary>({ knowledge: 0, worldbooks: 0, status: 'empty' });

  useEffect(() => {
    if (!currentSession?.session_id) {
      setSummary({ knowledge: 0, worldbooks: 0, status: 'empty' });
      onOpenChange(false);
      return;
    }
    let cancelled = false;
    async function loadCounts() {
      try {
        const [knowledgeBindings, worldbookResponse] = await Promise.all([
          api.listSessionKnowledgeBases(currentSession!.session_id),
          api.getSessionWorldbooks(currentSession!.session_id),
        ]);
        if (!cancelled) {
          setSummary(summarizeContextSources(knowledgeBindings, worldbookResponse.enabled_worldbooks));
        }
      } catch {
        if (!cancelled) setSummary({ knowledge: 0, worldbooks: 0, status: 'empty' });
      }
    }
    void loadCounts();
    return () => {
      cancelled = true;
    };
  }, [currentSession?.session_id, open, onOpenChange]);

  return (
    <>
      <button
        type="button"
        className={`status-pill context-sources-button ${contextSourcesStatusClass(summary.status)}`}
        disabled={!currentSession}
        onClick={() => onOpenChange(true)}
        title={t('chat:contextSources.tooltip', { knowledge: summary.knowledge, worldbooks: summary.worldbooks })}
        aria-label={t('chat:contextSources.tooltip', { knowledge: summary.knowledge, worldbooks: summary.worldbooks })}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        <span className="context-sources-dot" aria-hidden="true" />
        <Layers size={14} aria-hidden="true" />
      </button>
      {open && currentSession
        ? createPortal(
          <ContextSourcesModal
            sessionId={currentSession.session_id}
            onOpenSettings={onOpenSettings}
            onClose={() => onOpenChange(false)}
            onSummaryChange={setSummary}
          />,
          document.body,
        )
        : null}
    </>
  );
}

type ContextSourcesSummary = {
  knowledge: number;
  worldbooks: number;
  status: 'empty' | 'ready' | 'warning';
};

function summarizeContextSources(knowledgeBindings: SessionKnowledgeBinding[], worldbookBindings: SessionWorldbookBinding[]): ContextSourcesSummary {
  const enabledKnowledgeBindings = knowledgeBindings.filter((binding) => binding.enabled);
  const enabledWorldbookBindings = worldbookBindings.filter((binding) => binding.enabled);
  const hasWarning = enabledKnowledgeBindings.some((binding) => !isKnowledgeBaseUsable(binding.knowledge_base));
  const hasEnabled = enabledKnowledgeBindings.length > 0 || enabledWorldbookBindings.length > 0;
  return {
    knowledge: enabledKnowledgeBindings.length,
    worldbooks: enabledWorldbookBindings.length,
    status: hasWarning ? 'warning' : hasEnabled ? 'ready' : 'empty',
  };
}

function isKnowledgeBaseUsable(knowledgeBase: KnowledgeBase | null | undefined): boolean {
  if (!knowledgeBase?.enabled) return false;
  const status = (knowledgeBase.index_status || '').toLowerCase();
  return status === 'ready' || status === 'indexed' || status === 'usable';
}

function contextSourcesStatusClass(status: ContextSourcesSummary['status']): string {
  if (status === 'ready') return 'ok';
  if (status === 'warning') return 'warn';
  return '';
}

function ContextSourcesModal({
  sessionId,
  onOpenSettings,
  onClose,
  onSummaryChange,
}: {
  sessionId: string;
  onOpenSettings: () => void;
  onClose: () => void;
  onSummaryChange: (summary: ContextSourcesSummary) => void;
}) {
  const { t } = useTranslation();
  const modalRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const [activeTab, setActiveTab] = useState<'knowledge' | 'worldbooks'>('knowledge');
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [knowledgeBindings, setKnowledgeBindings] = useState<SessionKnowledgeBinding[]>([]);
  const [worldbooks, setWorldbooks] = useState<Worldbook[]>([]);
  const [worldbookBindings, setWorldbookBindings] = useState<SessionWorldbookBinding[]>([]);
  const [knowledgeStatus, setKnowledgeStatus] = useState<SaveStatus>({ state: 'idle', message: '' });
  const [worldbookStatus, setWorldbookStatus] = useState<SaveStatus>({ state: 'idle', message: '' });
  const [dragId, setDragId] = useState('');

  useEffect(() => {
    closeButtonRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape' && !dragId) onClose();
      if (event.key !== 'Tab' || !modalRef.current) return;
      const focusable = Array.from(modalRef.current.querySelectorAll<HTMLElement>('button:not(:disabled), [href], input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])'));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [dragId, onClose]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        setKnowledgeStatus({ state: 'idle', message: '' });
        setWorldbookStatus({ state: 'idle', message: '' });
        const [nextBases, nextKnowledgeBindings, nextWorldbooks] = await Promise.all([
          api.listKnowledgeBases(),
          api.listSessionKnowledgeBases(sessionId),
          api.getSessionWorldbooks(sessionId),
        ]);
        if (cancelled) return;
        setBases(nextBases);
        setKnowledgeBindings(nextKnowledgeBindings);
        setWorldbooks(nextWorldbooks.available_worldbooks);
        setWorldbookBindings(nextWorldbooks.enabled_worldbooks);
        onSummaryChange(summarizeContextSources(nextKnowledgeBindings, nextWorldbooks.enabled_worldbooks));
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : t('chat:contextSources.loadFailed');
          setKnowledgeStatus({ state: 'error', message });
          setWorldbookStatus({ state: 'error', message });
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [onSummaryChange, sessionId, t]);

  const selectedKnowledgeIds = useMemo(() => knowledgeBindings.filter((binding) => binding.enabled).map((binding) => binding.knowledge_base_id), [knowledgeBindings]);
  const selectedWorldbookIds = useMemo(() => worldbookBindings.filter((binding) => binding.enabled).map((binding) => binding.worldbook_id), [worldbookBindings]);
  const selectedKnowledgeSet = useMemo(() => new Set(selectedKnowledgeIds), [selectedKnowledgeIds]);
  const selectedWorldbookSet = useMemo(() => new Set(selectedWorldbookIds), [selectedWorldbookIds]);
  const enabledBases = selectedKnowledgeIds.map((id) => bases.find((base) => base.id === id)).filter((base): base is KnowledgeBase => Boolean(base));
  const availableBases = bases.filter((base) => !selectedKnowledgeSet.has(base.id));
  const enabledWorldbooks = selectedWorldbookIds.map((id) => worldbooks.find((worldbook) => worldbook.id === id)).filter((worldbook): worldbook is Worldbook => Boolean(worldbook));
  const availableWorldbooks = worldbooks.filter((worldbook) => !selectedWorldbookSet.has(worldbook.id));

  async function saveKnowledgeIds(nextIds: string[]) {
    const previousBindings = knowledgeBindings;
    setKnowledgeStatus({ state: 'saving', message: t('chat:contextSources.saving') });
    try {
      const nextBindings = await api.updateSessionKnowledgeBases(sessionId, nextIds);
      setKnowledgeBindings(nextBindings);
      onSummaryChange(summarizeContextSources(nextBindings, worldbookBindings));
      setKnowledgeStatus({ state: 'saved', message: t('chat:contextSources.saved') });
    } catch (err) {
      setKnowledgeBindings(previousBindings);
      setKnowledgeStatus({ state: 'error', message: err instanceof Error ? err.message : t('chat:contextSources.failedToSave') });
      void api.listSessionKnowledgeBases(sessionId).then(setKnowledgeBindings).catch(() => undefined);
    }
  }

  return (
    <div className="context-sources-backdrop" role="presentation" onMouseDown={() => { if (!dragId) onClose(); }}>
      <section
        className="context-sources-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="context-sources-title"
        ref={modalRef}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="context-sources-header">
          <div>
            <h2 id="context-sources-title">{t('chat:contextSources.title')}</h2>
            <p>{t('chat:contextSources.summary', { knowledge: selectedKnowledgeIds.length, worldbooks: selectedWorldbookIds.length })}</p>
          </div>
          <button ref={closeButtonRef} className="settings-secondary-button icon-only" type="button" onClick={onClose} aria-label={t('common:close')}><X size={16} /></button>
        </header>
        <div className="context-sources-tabs" role="tablist">
          <button type="button" role="tab" className={activeTab === 'knowledge' ? 'active' : ''} onClick={() => setActiveTab('knowledge')}>
            <BookOpen size={14} />
            {t('chat:contextSources.knowledgeBases')}
          </button>
          <button type="button" role="tab" className={activeTab === 'worldbooks' ? 'active' : ''} onClick={() => setActiveTab('worldbooks')}>
            <BookOpenText size={14} />
            {t('chat:contextSources.worldbooks')}
          </button>
        </div>
        {activeTab === 'knowledge' ? (
          <ContextSourceTab<KnowledgeBase>
            enabledTitle={t('chat:contextSources.enabled')}
            availableTitle={t('chat:contextSources.available')}
            enabledEmpty={t('chat:contextSources.noEnabledKnowledgeBases')}
            availableEmpty={t('chat:contextSources.noAvailableKnowledgeBases')}
            enabledItems={enabledBases}
            availableItems={availableBases}
            status={knowledgeStatus}
            isAvailable={(base) => base.enabled}
            isWarning={(base) => base.index_status !== 'ready'}
            statusLabel={(base) => !base.enabled ? t('chat:contextSources.disabled') : base.index_status !== 'ready' ? t('chat:contextSources.unavailable') : ''}
            getId={(base) => base.id}
            getName={(base) => base.name}
            onOpenSettings={onOpenSettings}
            onAdd={(base) => void saveKnowledgeIds([...selectedKnowledgeIds, base.id])}
            onRemove={(base) => void saveKnowledgeIds(selectedKnowledgeIds.filter((id) => id !== base.id))}
            onReorder={(nextItems) => void saveKnowledgeIds(nextItems.map((item) => item.id))}
            dragId={dragId}
            setDragId={setDragId}
          />
        ) : (
          <ContextSourceTab<Worldbook>
            enabledTitle={t('chat:contextSources.enabled')}
            availableTitle={t('chat:contextSources.available')}
            enabledEmpty={t('chat:contextSources.noEnabledWorldbooks')}
            availableEmpty={t('chat:contextSources.noAvailableWorldbooks')}
            enabledItems={enabledWorldbooks}
            availableItems={availableWorldbooks}
            status={worldbookStatus}
            isAvailable={(worldbook) => worldbook.enabled}
            isWarning={(worldbook) => !worldbook.enabled}
            statusLabel={(worldbook) => worldbook.enabled ? '' : t('chat:contextSources.disabled')}
            getId={(worldbook) => worldbook.id}
            getName={(worldbook) => worldbook.name}
            onOpenSettings={onOpenSettings}
            onAdd={(worldbook) => void saveWorldbookIds([...selectedWorldbookIds, worldbook.id])}
            onRemove={(worldbook) => void saveWorldbookIds(selectedWorldbookIds.filter((id) => id !== worldbook.id))}
            onReorder={(nextItems) => void saveWorldbookIds(nextItems.map((item) => item.id))}
            dragId={dragId}
            setDragId={setDragId}
          />
        )}
      </section>
    </div>
  );

  async function saveWorldbookIds(nextIds: string[]) {
    const previousBindings = worldbookBindings;
    setWorldbookStatus({ state: 'saving', message: t('chat:contextSources.saving') });
    try {
      const response = await api.updateSessionWorldbooks(sessionId, nextIds);
      setWorldbookBindings(response.enabled_worldbooks);
      setWorldbooks(response.available_worldbooks);
      onSummaryChange(summarizeContextSources(knowledgeBindings, response.enabled_worldbooks));
      const warningText = response.warnings?.length ? response.warnings.join(' ') : '';
      setWorldbookStatus({ state: 'saved', message: warningText || t('chat:contextSources.saved') });
    } catch (err) {
      setWorldbookBindings(previousBindings);
      setWorldbookStatus({ state: 'error', message: err instanceof Error ? err.message : t('chat:contextSources.failedToSave') });
      void api.getSessionWorldbooks(sessionId).then((response) => {
        setWorldbookBindings(response.enabled_worldbooks);
        setWorldbooks(response.available_worldbooks);
      }).catch(() => undefined);
    }
  }
}

type SaveStatus = { state: 'idle' | 'saving' | 'saved' | 'error'; message: string };

function ContextSourceTab<T>({
  enabledTitle,
  availableTitle,
  enabledEmpty,
  availableEmpty,
  enabledItems,
  availableItems,
  status,
  isAvailable,
  isWarning,
  statusLabel,
  getId,
  getName,
  onOpenSettings,
  onAdd,
  onRemove,
  onReorder,
  dragId,
  setDragId,
}: {
  enabledTitle: string;
  availableTitle: string;
  enabledEmpty: string;
  availableEmpty: string;
  enabledItems: T[];
  availableItems: T[];
  status: SaveStatus;
  isAvailable: (item: T) => boolean;
  isWarning: (item: T) => boolean;
  statusLabel: (item: T) => string;
  getId: (item: T) => string;
  getName: (item: T) => string;
  onOpenSettings: () => void;
  onAdd: (item: T) => void;
  onRemove: (item: T) => void;
  onReorder: (items: T[]) => void;
  dragId: string;
  setDragId: (id: string) => void;
}) {
  const { t } = useTranslation();
  const busy = status.state === 'saving';

  function dropOn(targetId: string) {
    if (!dragId || dragId === targetId || busy) return;
    const from = enabledItems.findIndex((item) => getId(item) === dragId);
    const to = enabledItems.findIndex((item) => getId(item) === targetId);
    if (from < 0 || to < 0) return;
    const nextItems = [...enabledItems];
    const [moved] = nextItems.splice(from, 1);
    nextItems.splice(to, 0, moved);
    onReorder(nextItems);
    setDragId('');
  }

  return (
    <div className="context-sources-body">
      {status.message ? <p className={`context-sources-feedback ${status.state}`}>{status.message}</p> : null}
      <section className="knowledge-picker-section">
        <h3>{enabledTitle}</h3>
        {enabledItems.length ? (
          <div className="knowledge-pill-list">
            {enabledItems.map((item) => {
              const id = getId(item);
              return (
                <button
                  key={id}
                  type="button"
                  className={`knowledge-pill enabled ${isWarning(item) ? 'danger' : ''} ${dragId === id ? 'dragging' : ''}`}
                  draggable={!busy}
                  disabled={busy}
                  onDragStart={(event) => {
                    setDragId(id);
                    event.dataTransfer.effectAllowed = 'move';
                  }}
                  onDragOver={(event) => {
                    if (dragId && dragId !== id) event.preventDefault();
                  }}
                  onDrop={(event) => {
                    event.preventDefault();
                    dropOn(id);
                  }}
                  onDragEnd={() => setDragId('')}
                  onClick={() => onRemove(item)}
                  title={t('chat:contextSources.dragToReorder')}
                >
                  <GripVertical size={13} className="knowledge-pill-drag" />
                  <span><strong>{getName(item)}</strong>{statusLabel(item) ? <small>{statusLabel(item)}</small> : null}</span>
                  <Minus size={14} className="knowledge-pill-action" />
                </button>
              );
            })}
          </div>
        ) : <p className="knowledge-picker-empty">{enabledEmpty}</p>}
      </section>
      <section className="knowledge-picker-section">
        <h3>{availableTitle}</h3>
        {availableItems.length ? (
          <div className="knowledge-pill-list">
            {availableItems.map((item) => {
              const available = isAvailable(item);
              return (
                <button
                  key={getId(item)}
                  type="button"
                  className={`knowledge-pill available ${isWarning(item) ? 'danger' : ''} ${available ? '' : 'disabled'}`}
                  disabled={busy || !available}
                  onClick={() => onAdd(item)}
                  title={available ? t('chat:contextSources.add') : statusLabel(item)}
                >
                  <span><strong>{getName(item)}</strong>{statusLabel(item) ? <small>{statusLabel(item)}</small> : null}</span>
                  <Plus size={14} className="knowledge-pill-action" />
                </button>
              );
            })}
          </div>
        ) : (
          <div className="settings-empty-state compact">
            {availableEmpty}
            <button type="button" className="settings-secondary-button" onClick={onOpenSettings} title={t('common:openSettings')}>{t('common:openSettings')}</button>
          </div>
        )}
      </section>
    </div>
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
