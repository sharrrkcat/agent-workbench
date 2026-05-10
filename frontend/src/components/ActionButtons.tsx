import { Loader2, Wand2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { actionKey, useWorkbenchStore } from '../store/useWorkbenchStore';
import type { AvailableAction } from '../types';

export function ActionButtons({ actions }: { actions: AvailableAction[] }) {
  const { t } = useTranslation();
  const invokeAction = useWorkbenchStore((state) => state.invokeAction);
  const pendingActionKey = useWorkbenchStore((state) => state.pendingActionKey);
  if (!actions.length) return null;

  return (
    <div className="action-buttons">
      {actions.map((action) => {
        const key = actionKey(action);
        const pending = pendingActionKey === key;
        return (
          <button key={key} onClick={() => void invokeAction(action)} disabled={Boolean(pendingActionKey)}>
            {pending ? <Loader2 size={13} className="spin" /> : <Wand2 size={13} />}
            {pending ? t('common:working') : action.label}
          </button>
        );
      })}
    </div>
  );
}
