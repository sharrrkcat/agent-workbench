import { Settings2 } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function ChatHeader({ onOpenSettings }: { onOpenSettings: (section?: 'general' | 'models' | 'knowledge' | 'worldbook' | 'pet') => void }) {
  const session = useWorkbenchStore((state) => state.currentSession);
  const updateSession = useWorkbenchStore((state) => state.updateSession);
  const profiles = useWorkbenchStore((state) => state.settings);
  const title = session?.title?.trim() || 'New session';
  const active = session?.waiting_run_id ? 'Waiting for your reply' : 'Chat';
  return (
    <header className="topbar compact-topbar">
      <div className="topbar-left">
        <div className="chat-title-block">
          <strong>{title}</strong>
          <small>{active}</small>
        </div>
        <label className="context-select">
          <span className="sr-only">Conversation mode</span>
          <select
            value={session?.context_mode || 'single_assistant'}
            disabled={!session}
            onChange={(event) => void updateSession({ context_mode: event.currentTarget.value as 'single_assistant' | 'group_transcript' })}
          >
            <option value="single_assistant">Single assistant</option>
            <option value="group_transcript">Group transcript</option>
          </select>
        </label>
      </div>
      <div className="topbar-actions">
        <span className="status-pill model-pill" title={session?.llm_profile_id || 'Global model default'}>
          {session?.llm_profile_id || 'Default model'}
        </span>
        {profiles?.utility_model_profile_id ? <span className="status-pill utility-pill">Utility ready</span> : null}
        <button className="icon-button" type="button" title="Settings" aria-label="Settings" onClick={() => onOpenSettings('general')}>
          <Settings2 size={18} />
        </button>
      </div>
    </header>
  );
}
