import { Settings } from 'lucide-react';
import { AgentSwitcher } from './AgentSwitcher';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function ChatHeader({ onOpenSettings }: { onOpenSettings: () => void }) {
  const currentSession = useWorkbenchStore((state) => state.currentSession);

  return (
    <header className="topbar">
      <div className="topbar-left">
        <AgentSwitcher />
        <span className="session-chip">
          {currentSession ? currentSession.title || `Session ${currentSession.session_id.slice(0, 6)}` : 'No session'}
        </span>
      </div>
      <div className="topbar-actions">
        <button className="tool-button" type="button" onClick={onOpenSettings} title="Open settings">
          <Settings size={17} />
          <span>Settings</span>
        </button>
      </div>
    </header>
  );
}
