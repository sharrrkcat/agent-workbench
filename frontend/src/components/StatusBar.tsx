import { CircleAlert, Loader2 } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function StatusBar() {
  const { loading, error, currentSession } = useWorkbenchStore();

  return (
    <footer className="status-bar">
      <span>{currentSession ? `Session ${currentSession.session_id.slice(0, 8)}` : 'No session'}</span>
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
