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
  const { t } = useTranslation('personas');
  const deleteMessage = useWorkbenchStore((state) => state.deleteMessage);
  const active = useWorkbenchStore((state) =>
    state.mutatingHistory || state.runs.some((run) => ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(run.status)),
  );
  const streaming = message.metadata?.streaming === true;
  const isUser = message.role === 'user';

  return (
    <div className="message-actions">
      {isUser && !editing ? (
        <button type="button" disabled={active} onClick={onEdit} title={t('editMessage')} aria-label={t('editMessage')}>
          <Pencil size={14} />
        </button>
      ) : null}
      {isUser && editing ? (
        <>
          <button type="button" onClick={() => void onSave()} disabled={busy || active}>
            {t('save')}
          </button>
          <button type="button" onClick={onCancel}>
            {t('cancel')}
          </button>
        </>
      ) : null}
      <MessageContextAction message={message} />
      <button
        type="button"
        disabled={streaming || active}
        onClick={() => {
          if (window.confirm(t('deleteMessageConfirm'))) void deleteMessage(message.message_id);
        }}
        title={t('deleteMessage')}
        aria-label={t('deleteMessage')}
      >
        <Trash2 size={14} />
      </button>
    </div>
  );
}

export function MessageContextAction({ message }: { message: Message }) {
  const { t } = useTranslation('personas');
  const selectContext = useWorkbenchStore((state) => state.setSourceMessageId);
  const selected = useWorkbenchStore((state) => state.sourceMessageId);
  const acceptsSelection = useWorkbenchStore((state) => state.currentSession?.effective.context_policy.mode === 'selected_message');
  if (!acceptsSelection || !isContextMessage(message)) return null;
  return <button type="button" className="icon-button context-action" aria-pressed={selected === message.message_id}
    title={t('selectContext')} aria-label={t('selectContext')}
    onClick={() => selectContext(selected === message.message_id ? null : message.message_id)}><MessageSquareQuote size={14} /></button>;
}
