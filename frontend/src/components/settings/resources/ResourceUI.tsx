import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Empty, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { flushSync } from 'react-dom';
import { RefreshCw } from 'lucide-react';
import type { ConfirmAction } from '@/hooks/useConfirmDialog';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/http';
import { readSettingsRoute, type NavigationTarget } from '../navigation';

export type LeaveGuard = (target: NavigationTarget) => Promise<boolean>;
export const SettingsLeaveContext = createContext<(guard: LeaveGuard) => () => void>(() => () => undefined);

export function useSettingsLeaveGuard(guard: LeaveGuard) {
  const register = useContext(SettingsLeaveContext);
  useEffect(() => register(guard), [guard, register]);
}

export function useResourceGuard(
  {
    section,
    detail,
    settings,
    busy,
    onLeaveDetail,
  }: {
    section: 'knowledge' | 'worldbook';
    detail: { dirty: boolean; busy: boolean };
    settings: { dirty: boolean; busy: boolean };
    busy: boolean;
    onLeaveDetail: () => void;
  },
  confirm: ConfirmAction,
) {
  const { t } = useTranslation('settings');
  const dirty = detail.dirty || settings.dirty;
  const locked = busy || detail.busy || settings.busy;
  const guard = useCallback(
    async (target: NavigationTarget) => {
      if (locked) return false;
      const withinSection =
        target.pathname === '/settings' && readSettingsRoute(target.search).section === section;
      if ((withinSection ? detail.dirty : dirty) && !(await confirm(t('resources.discardConfirm'))))
        return false;
      if (withinSection) onLeaveDetail();
      return true;
    },
    [locked, dirty, detail.dirty, section, onLeaveDetail, confirm, t],
  );
  useSettingsLeaveGuard(guard);
  useEffect(() => {
    if (!dirty && !locked) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, [dirty, locked]);
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
  if (!error && !notice) return null;
  return (
    <Alert
      className="resource-feedback"
      variant={error ? 'destructive' : 'default'}
      role={error ? 'alert' : 'status'}
    >
      <AlertDescription>{error || notice}</AlertDescription>
    </Alert>
  );
}

export function ResourceEmpty({ children }: { children: ReactNode }) {
  return (
    <Empty>
      <EmptyHeader>
        <EmptyTitle>{children}</EmptyTitle>
      </EmptyHeader>
    </Empty>
  );
}

export function ResourceLoading({ error, retry }: { error?: string; retry?: () => void }) {
  const { t } = useTranslation('settings');
  if (!error)
    return (
      <div className="resource-loading flex flex-col gap-3" role="status">
        <span className="sr-only">{t('common:loading')}</span>
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  return (
    <Alert className="resource-loading" variant="destructive">
      <AlertDescription>
        {error}
        {retry ? (
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
              <RefreshCw data-icon="inline-start" />
            </TooltipTrigger>
            <TooltipContent>{t('resources.refresh')}</TooltipContent>
          </Tooltip>
        ) : null}
      </AlertDescription>
    </Alert>
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
