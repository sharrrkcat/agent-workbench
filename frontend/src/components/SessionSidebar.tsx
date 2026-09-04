import { MessageSquarePlus, Settings2, Trash2 } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function SessionSidebar({ onOpenSettings }: { onOpenSettings: () => void }) {
  const sessions = useWorkbenchStore((state) => state.sessions);
  const current = useWorkbenchStore((state) => state.currentSession);
  const select = useWorkbenchStore((state) => state.selectSession);
  const create = useWorkbenchStore((state) => state.createSession);
  const remove = useWorkbenchStore((state) => state.deleteSession);
  return (
    <aside className="session-sidebar">
      <div className="sidebar-header"><strong>Workbench</strong><button className="icon-button" type="button" title="New session" aria-label="New session" onClick={() => void create()}><MessageSquarePlus size={18} /></button></div>
      <div className="session-list">
        {sessions.map((session) => <div key={session.session_id} className={`session-item ${session.session_id === current?.session_id ? 'selected' : ''}`}><button type="button" className="session-select" onClick={() => void select(session.session_id)}><span>{session.title.trim() || 'New session'}</span><small>{session.context_mode === 'group_transcript' ? 'Group' : 'Chat'}</small></button>{session.session_id === current?.session_id ? <button className="session-delete" type="button" title="Delete session" aria-label="Delete session" onClick={() => { if (window.confirm('Delete this session?')) void remove(session.session_id); }}><Trash2 size={14} /></button> : null}</div>)}
      </div>
      <div className="sidebar-footer"><button className="sidebar-settings-button" type="button" onClick={onOpenSettings}><Settings2 size={16} /> Settings</button></div>
    </aside>
  );
}
