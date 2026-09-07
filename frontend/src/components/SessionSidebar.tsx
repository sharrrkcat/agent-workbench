import { MessageSquarePlus, Settings2, Trash2, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function SessionSidebar({ onOpenSettings, open, onClose }: { onOpenSettings: () => void; open: boolean; onClose: () => void }) {
  const { t } = useTranslation('personas');
  const sessions = useWorkbenchStore((state) => state.sessions);
  const current = useWorkbenchStore((state) => state.currentSession);
  const select = useWorkbenchStore((state) => state.selectSession);
  const create = useWorkbenchStore((state) => state.createSession);
  const remove = useWorkbenchStore((state) => state.deleteSession);
  return (
    <aside className={`session-sidebar ${open ? 'mobile-open' : ''}`}>
      <div className="sidebar-header"><strong>Workbench</strong><button className="icon-button mobile-sidebar-toggle" type="button" title={t('close')} aria-label={t('close')} onClick={onClose}><X size={18} /></button><button className="icon-button" type="button" title={t('newSession')} aria-label={t('newSession')} onClick={() => { void create(); onClose(); }}><MessageSquarePlus size={18} /></button></div>
      <div className="session-list">
        {sessions.map((session) => <div key={session.session_id} className={`session-item ${session.session_id === current?.session_id ? 'selected' : ''}`}><button type="button" className="session-select" onClick={() => { void select(session.session_id); onClose(); }}><span>{session.title.trim() || t('newSession')}</span><small>{t(session.context_mode === 'group_transcript' ? 'group' : 'single')} / {session.effective.persona_name}</small></button>{session.session_id === current?.session_id ? <button className="session-delete" type="button" title={t('deleteSession')} aria-label={t('deleteSession')} onClick={() => { if (window.confirm(t('deleteSessionConfirm'))) void remove(session.session_id); }}><Trash2 size={14} /></button> : null}</div>)}
      </div>
      <div className="sidebar-footer"><button className="sidebar-settings-button" type="button" onClick={() => { onOpenSettings(); onClose(); }}><Settings2 size={16} />{t('settings')}</button></div>
    </aside>
  );
}
