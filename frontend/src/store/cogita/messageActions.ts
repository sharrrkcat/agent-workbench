import type { CogitaActions } from './state';
import { errorText, pruneHistoryState, runtimeResponseState, terminal } from './mergeState';
import { emptyQueue } from './messageQueue';

import { chatApi } from '../../api/chat';
import { projectsApi } from '../../api/projects';
import { knowledgeApi } from '../../api/knowledge';

export const createMessageActions: CogitaActions<
  'sendMessage' | 'deleteMessage' | 'editMessage' | 'setComposerDraftText'
> = (set, get, store) => ({
  sendMessage: async (content, attachments = [], queueItemId) => {
    if (get().sessionLoad && get().sessionLoad?.status !== 'ready') return false;
    let session = get().currentSession;
    const draft = get().chatDraft;
    const epoch = get().sessionEpoch;
    if ((!session && !draft) || get().sending || get().mutatingHistory || (!content.trim() && attachments.length === 0)) return false;
    const existingQueue = session ? get().messageQueues[session.session_id] : undefined;
    if (session && get().savingSessionIds.includes(session.session_id) || session?.waiting_run_id ||
        get().runs.some((run) => !terminal(run.status)) || existingQueue?.submission ||
        (!queueItemId && existingQueue?.items.length)) return false;
    const knowledgeIds = draft?.knowledge_base_ids ?? get().pendingKnowledge?.ids;
    const clientMessageId = crypto.randomUUID();
    let accepted = false;
    let submitted = false;
    const reserve = () => {
      if (!session) return;
      const sessionId = session.session_id;
      set((state) => {
        const queue = state.messageQueues[sessionId] ?? emptyQueue(session!.project_id, state.runs[state.runs.length - 1]);
        return { messageQueues: { ...state.messageQueues, [sessionId]: { ...queue,
          ...(!queueItemId ? { paused: null } : {}),
          submission: { clientId: clientMessageId, itemId: queueItemId, accepted: false, pending: true,
            boundary: state.sessionEpoch === epoch ? state.historyWindow?.items.slice(-1)[0]?.id : undefined },
        } } };
      });
    };
    const accept = () => {
      accepted = true;
      const sessionId = session?.session_id;
      set((state) => {
        const queue = sessionId ? state.messageQueues[sessionId] : undefined;
        return { ...(state.sessionEpoch === epoch ? { awaitingAcceptance: false } : {}),
          ...(sessionId && queue?.submission?.clientId === clientMessageId ? {
            messageQueues: { ...state.messageQueues, [sessionId]: { ...queue,
              submission: { ...queue.submission, accepted: true }, items: queue.items.filter((item) => item.id !== queueItemId),
            } },
          } : {}) };
      });
    };
    const unsubscribe = store.subscribe((state) => {
      const submission = session ? state.messageQueues[session.session_id]?.submission : null;
      if (!accepted && (submission?.clientId === clientMessageId && submission.accepted ||
        state.sessionEpoch === epoch && state.messages.some((message) =>
          message.role === 'user' && message.metadata?.client_message_id === clientMessageId))) accept();
    });
    set({ sending: true, awaitingAcceptance: !queueItemId, pendingClientMessageId: clientMessageId,
      ...(!queueItemId ? { composerDraftText: '' } : {}), error: null });
    reserve();
    try {
      if (session && get().historyWindow && !get().historyFollowing) {
        await get().loadHistory('latest');
        if (get().sessionEpoch !== epoch || get().error) return false;
      }
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
      const sessionId = session.session_id;
      if (queueItemId && (get().sessionEpoch !== epoch || get().queueTarget !== sessionId)) return false;
      if (!get().messageQueues[sessionId]?.submission) reserve();
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
      if (response.run) get().observeQueueRun(response.run);
      if (response.run) accept();
      if (get().sessionEpoch !== epoch) {
        if (get().currentSession?.session_id === sessionId) await get().refreshCurrent();
        return accepted;
      }
      set((state) => runtimeResponseState(state, response));
      if (!response.success && response.error && !response.run && get().currentSession?.session_id === session.session_id)
        set({ error: `${response.error_code || 'CHAT_FAILED'}: ${response.error}` });
      return accepted;
    } catch (error) {
      // A dropped POST response can follow persistence. Reconcile before restoring the input.
      if (submitted && session) {
        const sessionId = session.session_id;
        set((state) => {
          const queue = state.messageQueues[sessionId];
          return queue?.submission?.clientId === clientMessageId ? { messageQueues: { ...state.messageQueues, [sessionId]: {
            ...queue, submission: { ...queue.submission, pending: false },
          } } } : {};
        });
        await get().reconcileMessageQueue(sessionId);
        if (get().sessionEpoch === epoch) await get().refreshCurrent();
      }
      if (get().sessionEpoch === epoch) set({ error: errorText(error) });
      return accepted;
    } finally {
      unsubscribe();
      if (session) set((state) => {
        const sessionId = session!.session_id, queue = state.messageQueues[sessionId];
        if (queue?.submission?.clientId !== clientMessageId) return {};
        const unresolved = !accepted && !queue.submission.pending;
        return { messageQueues: { ...state.messageQueues, [sessionId]: { ...queue,
          submission: unresolved ? queue.submission : null,
          paused: unresolved ? queue.paused ?? 'unconfirmed' : !accepted && queue.items.length ? 'submission' : queue.paused,
        } } };
      });
      if (get().sessionEpoch === epoch) set({ sending: false, awaitingAcceptance: false, pendingClientMessageId: null,
        ...(!accepted && !queueItemId ? { composerDraftText: content } : {}) });
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

  setComposerDraftText: (text) => set((state) => {
    const sessionId = state.currentSession?.session_id, queue = sessionId ? state.messageQueues[sessionId] : undefined;
    return { composerDraftText: text, ...(sessionId && queue?.editing ? {
      messageQueues: { ...state.messageQueues, [sessionId]: { ...queue, editing: { ...queue.editing, content: text } } },
    } : {}) };
  }),

});
