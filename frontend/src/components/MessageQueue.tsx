import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pencil, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useCogitaStore } from '../store/useCogitaStore';

export function MessageQueue({ onEdit, onDelete, generating }: {
  onEdit: (id: string) => void; onDelete: (id: string) => void; generating: boolean;
}) {
  const { t } = useTranslation('chat');
  const queue = useCogitaStore((state) => state.currentSession ? state.messageQueues[state.currentSession.session_id] : undefined);
  const awaitingAcceptance = useCogitaStore((state) => state.awaitingAcceptance);
  const resume = useCogitaStore((state) => state.resumeMessageQueue);
  const [resuming, setResuming] = useState(false);
  if (!queue || (!queue.items.length && !(queue.paused && queue.submission))) return null;
  return <section className="message-queue flex min-w-0 flex-col gap-1" aria-label={t('queue.label')}>
    <div className="flex min-w-0 items-center justify-between gap-2">
      <span className="text-xs text-muted-foreground">{t('queue.title', { count: queue.items.length })}</span>
      {queue.paused ? <Button variant="ghost" size="sm" disabled={resuming || !!queue.submission?.pending}
        onClick={async () => { setResuming(true); try { await resume(); } finally { setResuming(false); } }}>
        {t('queue.resume')}
      </Button> : null}
    </div>
    {queue.paused || (!generating && queue.editing?.id === queue.items[0]?.id) ?
      <p className="text-xs text-muted-foreground" role="status">
        {queue.paused ? t(`queue.paused.${queue.paused}`) : t('queue.waitingEdit')}
      </p> : null}
    <ol className="queue-list flex min-w-0 flex-col gap-1 overflow-y-auto overscroll-contain">
      {queue.items.map((item, index) => {
        const editing = queue.editing?.id === item.id;
        const submitting = queue.submission?.itemId === item.id;
        const names = item.attachments.map((attachment) => attachment.name).join(', ');
        return <li key={item.id} data-queue-id={item.id} data-editing={editing}
          className="flex min-w-0 items-start gap-2 rounded-lg border px-2 py-1.5">
          <span className="pt-1 text-xs text-muted-foreground" aria-hidden="true">{index + 1}</span>
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            {item.content.trim() ? <p className="line-clamp-2 whitespace-pre-wrap break-words text-sm">{item.content}</p> : null}
            {names ? <p className="truncate text-xs text-muted-foreground" title={names}>
              {t('queue.attachments', { count: item.attachments.length })} · {names}
            </p> : null}
            {editing || submitting ? <Badge variant="secondary">{t(editing ? 'queue.editing' : 'queue.submitting')}</Badge> : null}
          </div>
          <div className="flex shrink-0 gap-1">
            <Tooltip>
              <TooltipTrigger render={<Button variant="ghost" size="icon-sm"
                aria-label={t('queue.edit', { number: index + 1 })}
                disabled={awaitingAcceptance || !!queue.editing || submitting} onClick={() => onEdit(item.id)} />}><Pencil /></TooltipTrigger>
              <TooltipContent>{t('queue.edit', { number: index + 1 })}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger render={<Button variant="ghost" size="icon-sm"
                aria-label={t('queue.remove', { number: index + 1 })}
                disabled={submitting} onClick={() => onDelete(item.id)} />}><Trash2 /></TooltipTrigger>
              <TooltipContent>{t('queue.remove', { number: index + 1 })}</TooltipContent>
            </Tooltip>
          </div>
        </li>;
      })}
    </ol>
  </section>;
}
