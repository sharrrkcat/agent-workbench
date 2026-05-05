import { MessageSquarePlus, MoreHorizontal, Sparkles } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function SessionSidebar() {
  const { sessions, currentSession, createSession, selectSession } = useWorkbenchStore();

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
      <button className="new-chat-button" onClick={() => void createSession()} type="button">
        <MessageSquarePlus size={17} />
        New Chat
      </button>
      <div className="session-list">
        {sessions.map((session) => {
          const active = currentSession?.session_id === session.session_id;
          return (
            <button
              key={session.session_id}
              className={`session-row ${active ? 'active' : ''}`}
              onClick={() => void selectSession(session.session_id)}
            >
              <span className="session-title">{session.title || `Session ${session.session_id.slice(0, 6)}`}</span>
              <span className="session-meta">
                <small>{session.default_agent_id}</small>
                <small>{formatUpdatedAt(session.updated_at)}</small>
              </span>
              <span className="session-menu" aria-hidden="true">
                <MoreHorizontal size={15} />
              </span>
            </button>
          );
        })}
      </div>
      <div className="sidebar-footer">Agents, commands, and local runs</div>
    </aside>
  );
}

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'updated';
  const diffMs = Date.now() - date.getTime();
  const minutes = Math.max(0, Math.round(diffMs / 60000));
  if (minutes < 1) return 'now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}
