import type { WorkbenchActions } from './state';
import { errorText, pruneHistoryState, runtimeResponseState } from './mergeState';

import { chatApi } from '../../api/chat';

export const createMessageActions: WorkbenchActions<
  'sendMessage' | 'deleteMessage' | 'editMessage' | 'setComposerDraftText' | 'setSourceMessageId'
> = (set, get) => ({
  sendMessage: async (content, attachments = []) => {
    const session = get().currentSession;
    const epoch = get().sessionEpoch;
    if (!session || get().sending || get().mutatingHistory || (!content.trim() && attachments.length === 0)) return undefined;
    set({ sending: true, error: null });
    try {
      const response = await chatApi.sendMessage(
        session.session_id,
        content,
        attachments,
        crypto.randomUUID(),
        get().sourceMessageId,
      );
      if (get().sessionEpoch !== epoch) return undefined;
      set((state) => runtimeResponseState(state, response));
      if (!response.success && response.error && !response.run && get().currentSession?.session_id === session.session_id)
        set({ error: `${response.error_code || 'CHAT_FAILED'}: ${response.error}` });
      return response.run
        ? {
            type: response.run.status === 'WAITING_FOR_USER' ? 'approval_requested' : 'run_completed',
            session_id: session.session_id,
            run_id: response.run.run_id,
          }
        : undefined;
    } catch (error) {
      if (get().sessionEpoch === epoch) set({ error: errorText(error) });
    } finally {
      if (get().sessionEpoch === epoch) set({ sending: false });
    }
    return undefined;
  },

  deleteMessage: async (messageId) => {
    if (get().mutatingHistory) return;
    const epoch = get().sessionEpoch;
    set({ mutatingHistory: true, error: null });
    try {
      const response = await chatApi.deleteMessage(messageId);
      if (get().sessionEpoch !== epoch) return;
      set((state) => pruneHistoryState(state, response));
      await get().refreshCurrent();
    } catch (error) {
      if (get().sessionEpoch === epoch) set({ error: errorText(error) });
    } finally {
      if (get().sessionEpoch === epoch) set({ mutatingHistory: false });
    }
  },

  editMessage: async (messageId, content, rerun = true) => {
    if (get().mutatingHistory) return;
    const epoch = get().sessionEpoch;
    set({ mutatingHistory: true, error: null });
    try {
      const response = await chatApi.editMessage(messageId, content, rerun);
      if (get().sessionEpoch !== epoch) return;
      set((state) => runtimeResponseState(state, response));
      await get().refreshCurrent();
    } catch (error) {
      if (get().sessionEpoch === epoch) set({ error: errorText(error) });
    } finally {
      if (get().sessionEpoch === epoch) set({ mutatingHistory: false });
    }
  },

  setComposerDraftText: (text) => set({ composerDraftText: text }),

  setSourceMessageId: (sourceMessageId) => set({ sourceMessageId }),
});
