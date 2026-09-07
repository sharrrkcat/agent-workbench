import { Check, Copy, RefreshCw, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import { terminal } from '../../store/workbench/mergeState';
import { MessageContextAction } from './MessageActions';
import { messageText } from './messageContent';
import type { Reply } from './turns';

export function ReplyActions({ reply }: { reply: Reply }) {
  const { t } = useTranslation('runs');
  const retry = useWorkbenchStore((state) => state.retryRun);
  const remove = useWorkbenchStore((state) => state.deleteRun);
  const setError = useWorkbenchStore((state) => state.setError);
  const busy = useWorkbenchStore((state) => state.mutatingHistory || state.runs.some((run) => !terminal(run.status)));
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
  return <div className="message-actions reply-actions">
    {body ? <button type="button" title={t(copied ? 'copied' : 'copyAnswer')} aria-label={t(copied ? 'copied' : 'copyAnswer')} onClick={() => void copy()}>{copied ? <Check size={14} /> : <Copy size={14} />}</button> : null}
    {reply.run.kind === 'chat' ? <button type="button" disabled={busy} title={t('retryReply')} aria-label={t('retryReply')} onClick={() => void retry(reply.run.run_id)}><RefreshCw size={14} /></button> : null}
    {reply.answer ? <MessageContextAction message={reply.answer} /> : null}
    <button type="button" disabled={busy} title={t('deleteReply')} aria-label={t('deleteReply')}
      onClick={() => { if (window.confirm(t('deleteReplyConfirm'))) void remove(reply.run.run_id); }}><Trash2 size={14} /></button>
  </div>;
}
