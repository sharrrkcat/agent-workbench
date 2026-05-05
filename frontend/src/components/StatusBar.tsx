import { CircleAlert, Loader2 } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function StatusBar() {
  const { loading, error, currentSession, health } = useWorkbenchStore();
  const llmModel = health?.llm?.model || '';

  return (
    <footer className="status-bar">
      <span className={health?.status === 'degraded' ? 'status-error' : 'status-item'}>
        Backend {health?.status || 'unknown'}
      </span>
      <span>{health?.version || 'version unknown'}</span>
      <span>{currentSession ? `Session ${currentSession.session_id.slice(0, 8)}` : 'No session'}</span>
      {llmModel ? <span>LLM {llmModel}</span> : null}
      {loading ? (
        <span className="status-item">
          <Loader2 size={14} className="spin" />
          Working
        </span>
      ) : null}
      {error ? (
        <span className="status-error">
          <CircleAlert size={14} />
          {error}
        </span>
      ) : null}
    </footer>
  );
}
