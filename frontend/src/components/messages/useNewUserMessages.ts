import { useLayoutEffect, useState } from 'react';
import { useCogitaStore } from '../../store/useCogitaStore';

// ChatView is keyed by sessionEpoch; draft promotion deliberately keeps that key.
export function useNewUserMessages() {
  const [animatedIds, setAnimatedIds] = useState<Set<string>>(() => new Set());
  useLayoutEffect(() => {
    const initial = useCogitaStore.getState();
    const seen = new Set(initial.messages.map((message) => message.message_id));
    return useCogitaStore.subscribe((state, previous) => {
      if (state.sessionEpoch !== initial.sessionEpoch) return;
      const added: string[] = [];
      for (const message of state.messages) {
        if (seen.has(message.message_id)) continue;
        seen.add(message.message_id);
        if ((state.sending || previous.sending) && message.role === 'user' &&
            message.session_id === state.currentSession?.session_id) added.push(message.message_id);
      }
      if (added.length) setAnimatedIds((ids) => new Set([...ids, ...added]));
    });
  }, []);
  return animatedIds;
}
