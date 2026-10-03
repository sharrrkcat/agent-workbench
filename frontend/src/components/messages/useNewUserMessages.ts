import { useLayoutEffect, useState } from 'react';
import { useCogitaStore } from '../../store/useCogitaStore';

// ChatView is keyed by sessionEpoch; draft promotion deliberately keeps that key.
export function useNewUserMessages() {
  const [animatedIds, setAnimatedIds] = useState<Set<string>>(() => new Set());
  useLayoutEffect(() => {
    const initial = useCogitaStore.getState();
    return useCogitaStore.subscribe((state) => {
      if (state.sessionEpoch !== initial.sessionEpoch) return;
      const visible = new Set(state.messages.map((m) => m.message_id));
      const added = state.messages.filter((m) => state.pendingClientMessageId &&
        m.role === 'user' && m.metadata?.client_message_id === state.pendingClientMessageId).map((m) => m.message_id);
      setAnimatedIds((ids) => {
        const retained = new Set([...ids].filter((id) => visible.has(id)));
        for (const id of added) retained.add(id);
        return retained.size === ids.size && [...retained].every((id) => ids.has(id)) ? ids : retained;
      });
    });
  }, []);
  return animatedIds;
}
