import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { MessageSquarePlus, Pencil, Settings, Sparkles, Trash2 } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { Session } from '../types';

export function SessionSidebar({ onOpenSettings }: { onOpenSettings: () => void }) {
  const { t } = useTranslation();
  const { sessions, currentSession, createSession, creatingSession, selectSession, deleteSession, renameSession } = useWorkbenchStore();

  function confirmDelete(sessionId: string) {
    const confirmed = window.confirm(t('chat:confirmDeleteSession'));
    if (confirmed) {
      void deleteSession(sessionId);
    }
  }

  return (
    <aside className="session-sidebar">
      <div className="sidebar-header">
        <div className="brand-mark">
          <Sparkles size={17} />
        </div>
        <div>
          <strong>Agent Workbench</strong>
          <span>{t('chat:appSubtitle')}</span>
        </div>
        <button className="sidebar-settings-button" type="button" title={t('common:openSettings')} aria-label={t('common:openSettings')} onClick={onOpenSettings}>
          <Settings size={16} />
        </button>
      </div>
      <button className="new-chat-button" onClick={() => void createSession()} type="button" disabled={creatingSession}>
        <MessageSquarePlus size={17} />
        {creatingSession ? t('common:creating') : t('chat:newChat')}
      </button>
      <div className="session-list">
        {sessions.map((session) => {
          const active = currentSession?.session_id === session.session_id;
          return (
            <SessionRow
              key={session.session_id}
              active={active}
              session={session}
              onDelete={confirmDelete}
              onRename={renameSession}
              onSelect={selectSession}
            />
          );
        })}
      </div>
      <div className="sidebar-footer">{t('chat:sidebarFooter')}</div>
    </aside>
  );
}

function SessionRow({
  active,
  session,
  onDelete,
  onRename,
  onSelect,
}: {
  active: boolean;
  session: Session;
  onDelete: (sessionId: string) => void;
  onRename: (sessionId: string, title: string) => Promise<void>;
  onSelect: (sessionId: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(session.title);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const label = session.title || `Session ${session.session_id.slice(0, 6)}`;

  useEffect(() => {
    if (!editing) {
      setDraft(session.title);
    }
  }, [editing, session.title]);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  async function saveRename() {
    const trimmed = draft.trim();
    if (!trimmed) {
      setDraft(session.title);
      setEditing(false);
      return;
    }
    if (trimmed === session.title) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onRename(session.session_id, trimmed);
      setEditing(false);
    } catch {
      // The store surfaces the floating error; keep the editor open.
    } finally {
      setSaving(false);
    }
  }

  function cancelRename() {
    setDraft(session.title);
    setEditing(false);
  }

  return (
    <div className={`session-row ${active ? 'active' : ''} ${editing ? 'editing' : ''}`}>
      {editing ? (
        <input
          ref={inputRef}
          className="session-title-input"
          value={draft}
          maxLength={120}
          disabled={saving}
          aria-label={t('chat:renameSession', { name: label })}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => void saveRename()}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              void saveRename();
            }
            if (event.key === 'Escape') {
              event.preventDefault();
              cancelRename();
            }
          }}
        />
      ) : (
        <button className="session-select-button" type="button" onClick={() => void onSelect(session.session_id)}>
          <span className="session-title">{label}</span>
        </button>
      )}
      <button
        className="session-rename-button"
        type="button"
        title={t('chat:renameSession', { name: label })}
        aria-label={t('chat:renameSession', { name: label })}
        disabled={saving}
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => setEditing(true)}
      >
        <Pencil size={14} />
      </button>
      <button
        className="session-delete-button"
        type="button"
        title={t('chat:deleteSession', { name: label })}
        aria-label={t('chat:deleteSession', { name: label })}
        disabled={saving}
        onClick={() => onDelete(session.session_id)}
      >
        <Trash2 size={14} />
      </button>
    </div>
  );
}
