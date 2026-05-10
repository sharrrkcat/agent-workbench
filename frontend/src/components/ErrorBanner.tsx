import { CircleAlert, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { formatApiError } from '../i18n/formatters';

export function ErrorBanner() {
  const { t } = useTranslation();
  const lastError = useWorkbenchStore((state) => state.lastError);
  const clearError = useWorkbenchStore((state) => state.clearError);
  if (!lastError) return null;
  const displayError = formatApiError(lastError, t, lastError.message);

  return (
    <div className="error-banner">
      <CircleAlert size={15} />
      <span>
        <strong>{lastError.code}</strong>
        {': '}
        {displayError.message}
      </span>
      <button type="button" onClick={clearError} title={t('common:dismiss')}>
        <X size={14} />
      </button>
    </div>
  );
}
