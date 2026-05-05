import { CircleAlert, X } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function ErrorBanner() {
  const lastError = useWorkbenchStore((state) => state.lastError);
  const clearError = useWorkbenchStore((state) => state.clearError);
  if (!lastError) return null;

  return (
    <div className="error-banner">
      <CircleAlert size={15} />
      <span>
        <strong>{lastError.code}</strong>
        {': '}
        {lastError.message}
      </span>
      <button type="button" onClick={clearError} title="Dismiss error">
        <X size={14} />
      </button>
    </div>
  );
}
