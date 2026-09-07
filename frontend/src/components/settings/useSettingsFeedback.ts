import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../api/http';

export type SettingsTask = (task: () => Promise<unknown>) => void;

export function useSettingsFeedback() {
  const { t } = useTranslation('settings');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const run: SettingsTask = (task) => {
    setError('');
    setMessage('');
    void task()
      .then(() => setMessage(t('saved')))
      .catch((reason) => {
        setError(reason instanceof ApiError ? `${reason.code}: ${reason.message}` : String(reason));
      });
  };
  return { message, error, run };
}
