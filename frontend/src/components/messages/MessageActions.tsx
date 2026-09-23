import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { MessageSquareQuote, Pencil, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { Message } from '../../types/messages';
import { isContextMessage } from './messageContent';

export function MessageActions({
  message,
  editing,
  busy,
  onEdit,
  onSave,
  onCancel,
}: {
  message: Message;
  editing: boolean;
  busy: boolean;
  onEdit: () => void;
  onSave: () => Promise<void>;
  onCancel: () => void;
}) {
  const { confirm, confirmation } = useConfirmDialog();
  const { t } = useTranslation('personas');
  const deleteMessage = useWorkbenchStore((state) => state.deleteMessage);
  const active = useWorkbenchStore(
    (state) =>
      state.mutatingHistory ||
      state.runs.some((run) => ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(run.status)),
  );
  const streaming = message.metadata?.streaming === true;
  const isUser = message.role === 'user';

  return (
    <div className="message-actions">
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
          <TooltipContent>{t('editMessage')}</TooltipContent>
        </Tooltip>
      ) : null}
      {isUser && editing ? (
        <>
          <Button type="button" onClick={() => void onSave()} disabled={busy || active} variant="ghost">
            {t('save')}
          </Button>
          <Button type="button" onClick={onCancel} variant="ghost">
            {t('cancel')}
          </Button>
        </>
      ) : null}
      <MessageContextAction message={message} />
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
        <TooltipContent>{t('deleteMessage')}</TooltipContent>
      </Tooltip>
      {confirmation}
    </div>
  );
}

export function MessageContextAction({ message }: { message: Message }) {
  const { t } = useTranslation('personas');
  const selectContext = useWorkbenchStore((state) => state.setSourceMessageId);
  const selected = useWorkbenchStore((state) => state.sourceMessageId);
  const acceptsSelection = useWorkbenchStore(
    (state) => state.currentSession?.effective.context_policy.mode === 'selected_message',
  );
  if (!acceptsSelection || !isContextMessage(message)) return null;
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            type="button"
            aria-pressed={selected === message.message_id}
            aria-label={t('selectContext')}
            onClick={() => selectContext(selected === message.message_id ? null : message.message_id)}
            variant="ghost"
            size="icon"
            className="context-action"
          />
        }
      >
        <MessageSquareQuote size={14} />
      </TooltipTrigger>
      <TooltipContent>{t('selectContext')}</TooltipContent>
    </Tooltip>
  );
}
