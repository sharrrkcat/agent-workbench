import type { CogitaActions } from './state';
import { errorText, pruneHistoryState, runtimeResponseState } from './mergeState';

import { chatApi } from '../../api/chat';
import { projectsApi } from '../../api/projects';
import { knowledgeApi } from '../../api/knowledge';

export const createMessageActions: CogitaActions<
  'sendMessage' | 'deleteMessage' | 'editMessage' | 'setComposerDraftText'
> = (set, get, store) => ({
  sendMessage: async (content, attachments = []) => {
    if (get().sessionLoad && get().sessionLoad?.status !== 'ready') return false;
    let session = get().currentSession;
    const draft = get().chatDraft;
    const epoch = get().sessionEpoch;
    if ((!session && !draft) || get().sending || get().mutatingHistory || (!content.trim() && attachments.length === 0)) return false;
    const knowledgeIds = draft?.knowledge_base_ids ?? get().pendingKnowledge?.ids;
    const clientMessageId = crypto.randomUUID();
    let accepted = false;
    let submitted = false;
    const accept = () => {
      accepted = true;
      set({ awaitingAcceptance: false });
    };
    const unsubscribe = store.subscribe((state) => {
      if (!accepted && state.sessionEpoch === epoch && state.messages.some((message) =>
        message.role === 'user' && message.metadata?.client_message_id === clientMessageId)) accept();
    });
    set({ sending: true, awaitingAcceptance: true, composerDraftText: '', error: null });
    try {
      if (!session && draft) {
        if (draft.kind === 'workspace') {
          session = await projectsApi.createSession(draft.project_id, { title: draft.title.trim(), overrides: draft.overrides });
        } else {
          const { kind: _kind, project_id: _projectId, user_persona: _user, knowledge_base_ids: _knowledge, ...values } = draft;
          session = await chatApi.createSession({ ...values, title: values.title.trim() });
        }
        const created = session;
        set((state) => ({
          sessions: [created, ...state.sessions.filter((item) => item.session_id !== created.session_id)],
          sessionVersion: state.sessionVersion + 1,
          ...(state.sessionEpoch === epoch ? { currentSession: created, chatDraft: null,
            lastOrdinarySessionId: created.kind === 'ordinary' ? created.session_id : state.lastOrdinarySessionId,
            pendingKnowledge: knowledgeIds?.length ? { sessionId: created.session_id, ids: knowledgeIds } : null } : {}),
        }));
      }
      if (!session) return false;
      if (knowledgeIds?.length) {
        await knowledgeApi.updateSessionKnowledgeBases(session.session_id, knowledgeIds);
        if (get().sessionEpoch === epoch) set({ pendingKnowledge: null });
      }
      submitted = true;
      const response = await chatApi.sendMessage(
        session.session_id,
        content,
        attachments,
        clientMessageId,
      );
      if (get().sessionEpoch !== epoch) return false;
      set((state) => runtimeResponseState(state, response));
      if (response.run) accept();
      if (!response.success && response.error && !response.run && get().currentSession?.session_id === session.session_id)
        set({ error: `${response.error_code || 'CHAT_FAILED'}: ${response.error}` });
      return accepted;
    } catch (error) {
      // A dropped POST response can follow persistence. Reconcile before restoring the input.
      if (!accepted && submitted && get().sessionEpoch === epoch) await get().refreshCurrent();
      if (get().sessionEpoch === epoch) set({ error: errorText(error) });
      return accepted;
    } finally {
      unsubscribe();
      if (get().sessionEpoch === epoch) set({ sending: false, awaitingAcceptance: false,
        ...(!accepted ? { composerDraftText: content } : {}) });
    }
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

  editMessage: async (messageId, content, attachmentIds, rerun = true) => {
    if (get().mutatingHistory) return false;
    const epoch = get().sessionEpoch;
    set({ mutatingHistory: true, error: null });
    try {
      const response = await chatApi.editMessage(messageId, content, attachmentIds, rerun);
      if (get().sessionEpoch !== epoch) return false;
      set((state) => runtimeResponseState(state, response));
      await get().refreshCurrent();
      return true;
    } catch (error) {
      if (get().sessionEpoch === epoch) set({ error: errorText(error) });
      return false;
    } finally {
      if (get().sessionEpoch === epoch) set({ mutatingHistory: false });
    }
  },

  setComposerDraftText: (text) => set({ composerDraftText: text }),

});
