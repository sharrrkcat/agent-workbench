import type { CogitaActions } from './state';
import { errorText, pruneHistoryState, runtimeResponseState } from './mergeState';

import { chatApi } from '../../api/chat';
import { projectsApi } from '../../api/projects';
import { knowledgeApi } from '../../api/knowledge';

export const createMessageActions: CogitaActions<
  'sendMessage' | 'deleteMessage' | 'editMessage' | 'setComposerDraftText' | 'setSourceMessageId'
> = (set, get) => ({
  sendMessage: async (content, attachments = []) => {
    if (get().sessionLoad && get().sessionLoad?.status !== 'ready') return undefined;
    let session = get().currentSession;
    const draft = get().chatDraft;
    const epoch = get().sessionEpoch;
    if ((!session && !draft) || get().sending || get().mutatingHistory || (!content.trim() && attachments.length === 0)) return undefined;
    const sourceMessageId = get().sourceMessageId;
    const knowledgeIds = draft?.knowledge_base_ids ?? get().pendingKnowledge?.ids;
    set({ sending: true, error: null });
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
      if (!session) return undefined;
      if (knowledgeIds?.length) {
        await knowledgeApi.updateSessionKnowledgeBases(session.session_id, knowledgeIds);
        if (get().sessionEpoch === epoch) set({ pendingKnowledge: null });
      }
      const response = await chatApi.sendMessage(
        session.session_id,
        content,
        attachments,
        crypto.randomUUID(),
        sourceMessageId,
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
