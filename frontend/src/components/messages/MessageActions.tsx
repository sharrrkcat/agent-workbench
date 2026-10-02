import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Pencil, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useCogitaStore } from '../../store/useCogitaStore';
import type { Message } from '../../types/messages';

export function MessageActions({
  message,
  editing,
  busy,
  canSave,
  onEdit,
  onSave,
  onCancel,
}: {
  message: Message;
  editing: boolean;
  busy: boolean;
  canSave: boolean;
  onEdit: () => void;
  onSave: () => Promise<void>;
  onCancel: () => void;
}) {
  const { confirm, confirmation } = useConfirmDialog();
  const { t } = useTranslation('personas');
  const deleteMessage = useCogitaStore((state) => state.deleteMessage);
  const active = useCogitaStore(
    (state) =>
      state.mutatingHistory ||
      state.runs.some((run) => ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(run.status)),
  );
  const streaming = message.metadata?.streaming === true;
  const isUser = message.role === 'user';

  return (
    <div className="message-actions" data-editing={editing}>
      {isUser && !editing ? (
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                type="button"
                disabled={active}
                onClick={onEdit}
                aria-label={t('editMessage')}
                variant="ghost"
                size="icon"
              />
            }
          >
            <Pencil size={14} />
          </TooltipTrigger>
          <TooltipContent side="bottom" collisionAvoidance={{ side: 'none', align: 'shift' }}>{t('editMessage')}</TooltipContent>
        </Tooltip>
      ) : null}
      {isUser && editing ? (
        <>
          <Button type="button" onClick={() => void onSave()} disabled={busy || active || !canSave} variant="ghost">
            {t('save')}
          </Button>
          <Button type="button" onClick={onCancel} variant="ghost">
            {t('cancel')}
          </Button>
        </>
      ) : null}
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              type="button"
              disabled={streaming || active}
              onClick={async () => {
                if (await confirm(t('deleteMessageConfirm'), { destructive: true }))
                  void deleteMessage(message.message_id);
              }}
              aria-label={t('deleteMessage')}
              variant="ghost"
              size="icon"
            />
          }
        >
          <Trash2 size={14} />
        </TooltipTrigger>
        <TooltipContent side="bottom" collisionAvoidance={{ side: 'none', align: 'shift' }}>{t('deleteMessage')}</TooltipContent>
      </Tooltip>
      {confirmation}
    </div>
  );
}
