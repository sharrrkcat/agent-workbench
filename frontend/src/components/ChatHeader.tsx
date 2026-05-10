import { BookOpen, Minus, MoreHorizontal, Plus, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import { AgentSwitcher } from './AgentSwitcher';
import { resolveCurrentLlmProfile, useWorkbenchStore } from '../store/useWorkbenchStore';
import { getModelProfileStatusLabel, getModelProfileStatusTitle } from '../i18n/formatters';
import { getModelProfileStatus, statusPillClass } from '../utils/modelStatus';
import type { ContextMode, KnowledgeBase, SessionKnowledgeBinding } from '../types';

export function ChatHeader({ onOpenSettings }: { onOpenSettings: () => void }) {
  const { t } = useTranslation();
  const currentSession = useWorkbenchStore((state) => state.currentSession);
  const state = useWorkbenchStore();
  const currentProfile = resolveCurrentLlmProfile(state);
  const modelStatus = getModelProfileStatus(currentProfile, state.llmProviderStatuses);
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const [sessionMenuOpen, setSessionMenuOpen] = useState(false);

  return (
    <header className="topbar">
      <div className="topbar-left">
        <AgentSwitcher />
        <span className="session-chip">
          {currentSession ? currentSession.title || t('chat:statusBar.session', { id: currentSession.session_id.slice(0, 6) }) : t('common:noSession')}
        </span>
      </div>
      <div className="topbar-actions">
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

function SessionMenu({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation();
  const currentSession = useWorkbenchStore((state) => state.currentSession);
  const deleteSession = useWorkbenchStore((state) => state.deleteSession);
  const updateSessionContextMode = useWorkbenchStore((state) => state.updateSessionContextMode);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const contextMode = currentSession?.context_mode === 'group_transcript' ? 'group_transcript' : 'single_assistant';

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
      {open ? (
        <div className="session-menu" role="menu">
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
          <button type="button" role="menuitem" className="session-menu-item danger" onClick={confirmDelete}>
            <Trash2 size={14} />
            <span>{t('chat:deleteSession', { name: '' }).trim()}</span>
          </button>
        </div>
      ) : null}
    </div>
  );
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
      {open ? (
        <div className="knowledge-picker-menu">
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
