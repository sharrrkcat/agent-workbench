import { Wand2 } from 'lucide-react';
import { actionKey, useWorkbenchStore } from '../store/useWorkbenchStore';
import type { AvailableAction } from '../types';

export function ActionButtons({ actions }: { actions: AvailableAction[] }) {
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
            <Wand2 size={14} />
            {pending ? 'Working...' : action.label}
          </button>
        );
      })}
    </div>
  );
}
