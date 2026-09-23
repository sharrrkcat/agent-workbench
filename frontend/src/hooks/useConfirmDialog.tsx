import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';

type Options = { destructive?: boolean; confirmLabel?: string; title?: string };
export type ConfirmAction = (message: string, options?: Options) => Promise<boolean>;

export function useConfirmDialog() {
  const { t } = useTranslation('common');
  const [request, setRequest] = useState<Options & { message: string }>();
  const [open, setOpen] = useState(false);
  const pending = useRef<((answer: boolean) => void) | null>(null);
  const cancel = useRef<HTMLButtonElement | null>(null);
  const confirm: ConfirmAction = useCallback((message, options = {}) => {
    if (pending.current) return Promise.resolve(false);
    return new Promise<boolean>((resolve) => {
      pending.current = resolve;
      setRequest({ ...options, message });
      setOpen(true);
    });
  }, []);
  const finish = useCallback((answer: boolean) => {
    const resolve = pending.current;
    pending.current = null;
    setOpen(false);
    resolve?.(answer);
  }, []);
  useEffect(
    () => () => {
      pending.current?.(false);
      pending.current = null;
    },
    [],
  );
  const confirmation = (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) finish(false);
      }}
    >
      <AlertDialogContent initialFocus={cancel}>
        <AlertDialogHeader>
          <AlertDialogTitle>{request?.title || t('confirmAction')}</AlertDialogTitle>
          <AlertDialogDescription className="whitespace-pre-line">{request?.message}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel ref={cancel} onClick={() => finish(false)}>
            {t('cancel')}
          </AlertDialogCancel>
          <AlertDialogAction
            type="button"
            variant={request?.destructive ? 'destructive' : 'default'}
            onClick={() => finish(true)}
          >
            {request?.confirmLabel || t('confirm')}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
  return { confirm, confirmation };
}
