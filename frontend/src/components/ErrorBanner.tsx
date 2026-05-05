import { CircleAlert } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function ErrorBanner() {
  const error = useWorkbenchStore((state) => state.error);
  if (!error) return null;

  return (
    <div className="error-banner">
      <CircleAlert size={15} />
      <span>{error}</span>
    </div>
  );
}
