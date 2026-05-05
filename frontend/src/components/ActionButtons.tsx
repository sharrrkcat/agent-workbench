import { Wand2 } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { AvailableAction } from '../types';

export function ActionButtons({ actions }: { actions: AvailableAction[] }) {
  const invokeAction = useWorkbenchStore((state) => state.invokeAction);
  const loading = useWorkbenchStore((state) => state.loading);
  if (!actions.length) return null;

  return (
    <div className="action-buttons">
      {actions.map((action) => (
        <button key={`${action.source_message_id}-${action.action_id}`} onClick={() => void invokeAction(action)} disabled={loading}>
          <Wand2 size={14} />
          {action.label}
        </button>
      ))}
    </div>
  );
}
