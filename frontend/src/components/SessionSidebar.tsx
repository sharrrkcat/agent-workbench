import { MessageSquarePlus } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function SessionSidebar() {
  const { sessions, currentSession, createSession, selectSession } = useWorkbenchStore();

  return (
    <aside className="session-sidebar">
      <div className="sidebar-header">
        <span>Sessions</span>
        <button className="icon-button" onClick={() => void createSession()} title="Create session">
          <MessageSquarePlus size={17} />
        </button>
      </div>
      <div className="session-list">
        {sessions.map((session) => {
          const active = currentSession?.session_id === session.session_id;
          return (
            <button
              key={session.session_id}
              className={`session-row ${active ? 'active' : ''}`}
              onClick={() => void selectSession(session.session_id)}
            >
              <span>{session.title || `Session ${session.session_id.slice(0, 6)}`}</span>
              <small>{session.default_agent_id}</small>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
