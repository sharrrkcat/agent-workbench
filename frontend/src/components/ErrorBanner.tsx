import { Button } from '@/components/ui/button';
import { X } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function ErrorBanner() {
  const error = useWorkbenchStore((state) => state.error);
  const setError = useWorkbenchStore((state) => state.setError);
  if (!error) return null;
  return (
    <div className="error-banner" role="alert">
      <span>{error}</span>
      <Button type="button" aria-label="Dismiss" onClick={() => setError(null)} variant="ghost" size="icon">
        <X size={15} />
      </Button>
    </div>
  );
}
