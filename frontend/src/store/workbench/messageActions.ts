import type { WorkbenchActions } from './state';
import { errorText, mergeMessages, toolResponseState } from './mergeState';

import { chatApi } from '../../api/chat';

export const createMessageActions: WorkbenchActions<
  'sendMessage' | 'deleteMessage' | 'retryMessage' | 'editMessage' | 'setComposerDraftText' | 'setSourceMessageId'
> = (set, get) => ({
  sendMessage: async (content, attachments = []) => {
    const session = get().currentSession;
    if (!session || (!content.trim() && attachments.length === 0)) return undefined;
    set({ sending: true, error: null });
    try {
      const response = await chatApi.sendMessage(
        session.session_id,
        content,
        attachments,
        crypto.randomUUID(),
        get().sourceMessageId,
      );
      if (response.run && response.session)
        set((state) =>
          toolResponseState(state, {
            run: response.run!,
            session: response.session!,
            messages: response.messages || [],
          }),
        );
      if (!response.success && response.error && get().currentSession?.session_id === session.session_id)
        set({ error: `${response.error_code || 'CHAT_FAILED'}: ${response.error}` });
      return response.success && response.run
        ? {
            type: response.run.status === 'WAITING_FOR_USER' ? 'approval_requested' : 'run_completed',
            session_id: session.session_id,
            run_id: response.run.run_id,
          }
        : undefined;
    } catch (error) {
      set({ error: errorText(error) });
    } finally {
      set({ sending: false });
    }
    return undefined;
  },

  deleteMessage: async (messageId) => {
    try {
      await chatApi.deleteMessage(messageId);
      set((state) => ({
        messages: state.messages.filter((item) => item.message_id !== messageId),
        sourceMessageId: state.sourceMessageId === messageId ? null : state.sourceMessageId,
      }));
    } catch (error) {
      set({ error: errorText(error) });
    }
  },

  retryMessage: async (messageId) => {
    try {
      const response = await chatApi.retryMessage(messageId);
      if (response.messages?.length && response.session?.session_id === get().currentSession?.session_id)
        set((state) => ({ messages: mergeMessages(state.messages, response.messages || []) }));
      await get().refreshCurrent();
    } catch (error) {
      set({ error: errorText(error) });
    }
  },

  editMessage: async (messageId, content, rerun = true) => {
    try {
      const response = await chatApi.editMessage(messageId, content, rerun);
      if (response.messages?.length && response.session?.session_id === get().currentSession?.session_id)
        set((state) => ({ messages: mergeMessages(state.messages, response.messages || []) }));
      await get().refreshCurrent();
    } catch (error) {
      set({ error: errorText(error) });
    }
  },

  setComposerDraftText: (text) => set({ composerDraftText: text }),

  setSourceMessageId: (sourceMessageId) => set({ sourceMessageId }),
});
