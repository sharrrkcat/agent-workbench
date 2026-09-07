import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/http';
import type { ModelTask } from './types';

export function useModelFeedback(reload: () => Promise<void>) {
  const { t } = useTranslation('llm');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const run: ModelTask = async (task, refresh = true) => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await task();
      if (refresh) await reload();
      setNotice(t('saved'));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.code + ': ' + reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, notice, run, setError };
}
