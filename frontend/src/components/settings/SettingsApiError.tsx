import { ApiError } from '../../api/client';

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
  const hasDetails = error.details && Object.keys(error.details).length > 0;
  return (
    <div className="settings-error-box" role="alert">
      <strong>{error.code}</strong>
      <span>{error.message}</span>
      {hasDetails ? (
        <details>
          <summary>Details</summary>
          <pre>{JSON.stringify(error.details, null, 2)}</pre>
        </details>
      ) : null}
    </div>
  );
}
