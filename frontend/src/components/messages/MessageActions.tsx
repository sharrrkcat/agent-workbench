import { MessageSquareQuote, Pencil, RefreshCw, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { Message } from '../../types/messages';

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
  const retryMessage = useWorkbenchStore((state) => state.retryMessage);
  const selectContext = useWorkbenchStore((state) => state.setSourceMessageId);
  const selectedContext = useWorkbenchStore((state) => state.sourceMessageId);
  const acceptsSelection = useWorkbenchStore(
    (state) => state.currentSession?.effective.context_policy.mode === 'selected_message',
  );
  const active = useWorkbenchStore((state) =>
    state.runs.some((run) => ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(run.status)),
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
      {message.role === 'assistant' && !message.parts.some((part) => part.type === 'tool_call') ? (
        <button
          type="button"
          disabled={streaming || active}
          onClick={() => void retryMessage(message.message_id)}
          title={t('retry')}
          aria-label={t('retry')}
        >
          <RefreshCw size={14} />
        </button>
      ) : null}
      {acceptsSelection &&
      ['user', 'assistant', 'tool'].includes(message.role) &&
      !message.metadata?.event_type &&
      !message.parts.some((part) => part.type === 'error') ? (
        <button
          type="button"
          disabled={streaming}
          aria-pressed={selectedContext === message.message_id}
          title={t('selectContext')}
          aria-label={t('selectContext')}
          onClick={() => selectContext(selectedContext === message.message_id ? null : message.message_id)}
        >
          <MessageSquareQuote size={14} />
        </button>
      ) : null}
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
