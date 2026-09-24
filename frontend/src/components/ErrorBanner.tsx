import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Alert, AlertAction, AlertDescription } from '@/components/ui/alert';
import { X } from 'lucide-react';
import { useCogitaStore } from '../store/useCogitaStore';

export function ErrorBanner() {
  const { t } = useTranslation('common');
  const error = useCogitaStore((state) => state.error);
  const setError = useCogitaStore((state) => state.setError);
  if (!error) return null;
  return (
    <Alert className="error-banner" variant="destructive">
      <AlertDescription>{error}</AlertDescription>
      <AlertAction>
        <Button
          type="button"
          aria-label={t('dismiss')}
          onClick={() => setError(null)}
          variant="ghost"
          size="icon"
        >
          <X />
        </Button>
      </AlertAction>
    </Alert>
  );
}
