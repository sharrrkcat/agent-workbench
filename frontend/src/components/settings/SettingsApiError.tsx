import { ApiError } from '../../api/client';
import { useTranslation } from 'react-i18next';
import { formatApiError } from '../../i18n/formatters';

export type SettingsErrorValue = {
  code: string;
  message: string;
  details?: Record<string, unknown>;
};

export function toSettingsError(error: unknown, fallback: string): SettingsErrorValue {
  if (error instanceof ApiError) {
    return { code: error.code, message: error.message, details: error.details };
  }
  if (error instanceof Error) {
    return { code: error.name || 'ERROR', message: error.message };
  }
  return { code: 'ERROR', message: fallback };
}

export function SettingsApiError({ error }: { error: SettingsErrorValue }) {
  const { t } = useTranslation(['errors', 'common']);
  const display = formatApiError(error, t, error.message);
  const hasDetails = error.details && Object.keys(error.details).length > 0;
  return (
    <div className="settings-error-box" role="alert">
      <strong>{display.code}</strong>
      <span>{display.message}</span>
      {hasDetails || display.originalMessage ? (
        <details>
          <summary>{t('common:details', { defaultValue: 'Details' })}</summary>
          <pre>{JSON.stringify({ code: error.code, message: error.message, details: error.details || {} }, null, 2)}</pre>
        </details>
      ) : null}
    </div>
  );
}
