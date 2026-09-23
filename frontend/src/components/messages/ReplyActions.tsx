import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { Switch } from '@/components/ui/switch';
import { Field, FieldLabel } from '@/components/ui/field';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Copy, RefreshCw, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import { terminal } from '../../store/workbench/mergeState';
import { MessageContextAction } from './MessageActions';
import { messageText } from './messageContent';
import type { Reply } from './turns';

export function ReplyActions({ reply }: { reply: Reply }) {
  const { confirm, confirmation } = useConfirmDialog();
  const { t } = useTranslation('runs');
  const retry = useWorkbenchStore((state) => state.retryRun);
  const remove = useWorkbenchStore((state) => state.deleteRun);
  const setError = useWorkbenchStore((state) => state.setError);
  const busy = useWorkbenchStore(
    (state) => state.mutatingHistory || state.runs.some((run) => !terminal(run.status)),
  );
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);
  const body = reply.answer ? messageText(reply.answer) : '';
  async function copy() {
    try {
      await navigator.clipboard.writeText(body);
      setCopied(true);
    } catch {
      setError(t('copyFailed'));
    }
  }
  return (
    <div className="message-actions reply-actions">
      {body ? (
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                type="button"
                aria-label={t(copied ? 'copied' : 'copyAnswer')}
                onClick={() => void copy()}
                variant="ghost"
              />
            }
          >
            {copied ? (
              <Field orientation="horizontal">
                <Switch onCheckedChange={undefined} />
                <FieldLabel>{''}</FieldLabel>
              </Field>
            ) : (
              <Copy size={14} />
            )}
          </TooltipTrigger>
          <TooltipContent>{t(copied ? 'copied' : 'copyAnswer')}</TooltipContent>
        </Tooltip>
      ) : null}
      {reply.run.kind === 'chat' ? (
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                type="button"
                disabled={busy}
                aria-label={t('retryReply')}
                onClick={() => void retry(reply.run.run_id)}
                variant="ghost"
                size="icon"
              />
            }
          >
            <RefreshCw size={14} />
          </TooltipTrigger>
          <TooltipContent>{t('retryReply')}</TooltipContent>
        </Tooltip>
      ) : null}
      {reply.answer ? <MessageContextAction message={reply.answer} /> : null}
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              type="button"
              disabled={busy}
              aria-label={t('deleteReply')}
              onClick={async () => {
                if (await confirm(t('deleteReplyConfirm'), { destructive: true }))
                  void remove(reply.run.run_id);
              }}
              variant="ghost"
              size="icon"
            />
          }
        >
          <Trash2 size={14} />
        </TooltipTrigger>
        <TooltipContent>{t('deleteReply')}</TooltipContent>
      </Tooltip>
      {confirmation}
    </div>
  );
}
