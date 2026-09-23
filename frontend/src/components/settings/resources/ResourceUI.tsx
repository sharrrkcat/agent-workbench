import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import { RefreshCw } from 'lucide-react';
import type { ConfirmAction } from '@/hooks/useConfirmDialog';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/http';

export type LeaveGuard = () => Promise<boolean>;
export const SettingsLeaveContext = createContext<(guard: LeaveGuard) => () => void>(() => () => undefined);

export function useResourceGuard(dirty: boolean, busy: boolean, confirm: ConfirmAction) {
  const { t } = useTranslation('settings');
  const register = useContext(SettingsLeaveContext);
  const guard = useCallback(
    async () => !busy && (!dirty || (await confirm(t('resources.discardConfirm')))),
    [busy, dirty, confirm, t],
  );
  useEffect(() => register(guard), [guard, register]);
  useEffect(() => {
    if (!dirty && !busy) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, [dirty, busy]);
  return guard;
}

export function errorText(error: unknown) {
  return error instanceof ApiError ? `${error.code}: ${error.message}` : String(error);
}

export function useResourceTask() {
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const lock = useRef(false);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  async function run<T>(key: string, action: () => Promise<T>, message = ''): Promise<T | undefined> {
    if (lock.current) return;
    lock.current = true;
    setBusy(key);
    setError('');
    setNotice('');
    try {
      const result = await action();
      if (live.current) setNotice(message);
      return result;
    } catch (reason) {
      if (live.current) setError(errorText(reason));
    } finally {
      lock.current = false;
      if (live.current) setBusy('');
    }
  }
  return { busy, error, notice, setError, setNotice, run };
}

export function Feedback({ error, notice }: { error: string; notice?: string }) {
  return (
    <div className="resource-feedback" role={error ? 'alert' : 'status'}>
      {error ? <span className="error-text">{error}</span> : <span className="success-text">{notice}</span>}
    </div>
  );
}

export function ResourceLoading({ error, retry }: { error?: string; retry?: () => void }) {
  const { t } = useTranslation('settings');
  return (
    <div className="resource-loading" role={error ? 'alert' : 'status'}>
      {error || t('common:loading')}
      {error && retry ? (
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={t('resources.refresh')}
                onClick={retry}
              />
            }
          >
            <RefreshCw size={16} />
          </TooltipTrigger>
          <TooltipContent>{t('resources.refresh')}</TooltipContent>
        </Tooltip>
      ) : null}
    </div>
  );
}

export function equalDraft(left: unknown, right: unknown) {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function revealInvalidField(event: { target: EventTarget }) {
  if (!(event.target instanceof HTMLElement)) return;
  const target = event.target;
  flushSync(() => {
    let panel = target.closest('[data-slot="collapsible"]');
    while (panel) {
      const trigger = panel.querySelector<HTMLElement>(':scope > [data-slot="collapsible-trigger"]');
      if (trigger?.getAttribute('aria-expanded') === 'false') trigger.click();
      panel = panel.parentElement?.closest('[data-slot="collapsible"]') ?? null;
    }
  });
  target.focus();
}
