import { MessageSquarePlus, Sparkles, Trash2 } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function SessionSidebar() {
  const { sessions, currentSession, createSession, creatingSession, selectSession, deleteSession } = useWorkbenchStore();

  function confirmDelete(sessionId: string) {
    const confirmed = window.confirm('Delete this session?\nThis will remove its messages and runs.');
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
          <span>Local AI console</span>
        </div>
      </div>
      <button className="new-chat-button" onClick={() => void createSession()} type="button" disabled={creatingSession}>
        <MessageSquarePlus size={17} />
        {creatingSession ? 'Creating...' : 'New Chat'}
      </button>
      <div className="session-list">
        {sessions.map((session) => {
          const active = currentSession?.session_id === session.session_id;
          return (
            <div key={session.session_id} className={`session-row ${active ? 'active' : ''}`}>
              <button className="session-select-button" type="button" onClick={() => void selectSession(session.session_id)}>
                <span className="session-title">{session.title || `Session ${session.session_id.slice(0, 6)}`}</span>
              </button>
              <button
                className="session-delete-button"
                type="button"
                title="Delete session"
                aria-label={`Delete ${session.title || `Session ${session.session_id.slice(0, 6)}`}`}
                onClick={() => confirmDelete(session.session_id)}
              >
                <Trash2 size={14} />
              </button>
            </div>
          );
        })}
      </div>
      <div className="sidebar-footer">Agents, commands, and local runs</div>
    </aside>
  );
}
