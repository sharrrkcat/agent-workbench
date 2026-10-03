import { chatApi } from '../../api/chat';
import { runsApi } from '../../api/runs';
import type { CogitaActions } from './state';
import { emptyQueue, mergeQueueRuntime, type MessageQueue } from './messageQueue';
import { errorText, terminal } from './mergeState';

export const createQueueActions: CogitaActions<
  'enqueueMessage' | 'beginQueuedEdit' | 'saveQueuedEdit' | 'setQueuedEditAttachments' | 'deleteQueuedMessage' |
  'resumeMessageQueue' | 'dispatchQueuedMessage' | 'reconcileMessageQueue' | 'observeQueueRun'
> = (set, get) => {
  function update(sessionId: string, change: (queue: MessageQueue) => MessageQueue) {
    set((state) => {
      const queue = state.messageQueues[sessionId];
      return queue ? { messageQueues: { ...state.messageQueues, [sessionId]: change(queue) } } : {};
    });
  }
  return {
    enqueueMessage: (content, attachments = []) => {
      const state = get(), session = state.currentSession;
      if (!session || state.awaitingAcceptance || state.mutatingHistory ||
          state.sessionLoad && state.sessionLoad.status !== 'ready' || (!content.trim() && !attachments.length)) return false;
      const queue = state.messageQueues[session.session_id] ?? emptyQueue(session.project_id, state.runs[state.runs.length - 1]);
      set({ composerDraftText: '', messageQueues: { ...state.messageQueues, [session.session_id]: {
        ...queue, items: [...queue.items, { id: crypto.randomUUID(), content, attachments }],
      } } });
      return true;
    },
    beginQueuedEdit: (id) => {
      const state = get(), sessionId = state.currentSession?.session_id;
      const queue = sessionId ? state.messageQueues[sessionId] : undefined;
      const item = queue?.items.find((item) => item.id === id);
      if (!sessionId || !queue || !item || queue.editing || queue.submission?.itemId === id || state.awaitingAcceptance) return false;
      set({ composerDraftText: item.content, messageQueues: { ...state.messageQueues, [sessionId]: {
        ...queue, editing: { id, content: item.content,
          attachments: item.attachments.map((attachment) => ({ ...attachment, status: 'ready', attachment })) },
      } } });
      return true;
    },
    saveQueuedEdit: () => {
      const state = get(), sessionId = state.currentSession?.session_id;
      const queue = sessionId ? state.messageQueues[sessionId] : undefined;
      const edit = queue?.editing;
      if (!sessionId || !queue || !edit || edit.attachments.some((item) => item.status !== 'ready') ||
          (!edit.content.trim() && !edit.attachments.length)) return false;
      const attachments = edit.attachments.flatMap((item) => item.attachment ? [item.attachment] : []);
      set({ composerDraftText: '', messageQueues: { ...state.messageQueues, [sessionId]: { ...queue, editing: null,
        items: queue.items.map((item) => item.id === edit.id ? { ...item, content: edit.content, attachments } : item),
      } } });
      return true;
    },
    setQueuedEditAttachments: (sessionId, id, change) => update(sessionId, (queue) => queue.editing?.id === id
      ? { ...queue, editing: { ...queue.editing, attachments: change(queue.editing.attachments) } } : queue),
    deleteQueuedMessage: (id) => {
      const state = get(), sessionId = state.currentSession?.session_id;
      const queue = sessionId ? state.messageQueues[sessionId] : undefined;
      if (!sessionId || !queue || queue.submission?.itemId === id) return;
      const editing = queue.editing?.id === id;
      const items = queue.items.filter((item) => item.id !== id);
      set({ ...(editing ? { composerDraftText: '' } : {}), messageQueues: { ...state.messageQueues, [sessionId]: {
        ...queue, items, editing: editing ? null : queue.editing,
      } } });
    },
    observeQueueRun: (run) => set((state) => ({ messageQueues: mergeQueueRuntime(state.messageQueues, [run], []) })),
    reconcileMessageQueue: async (sessionId) => {
      const queue = get().messageQueues[sessionId];
      if (!queue) return true;
      try {
        const submission = queue.submission;
        if (submission && !submission.pending) {
          let page = await chatApi.getHistory(sessionId);
          // Search only pages since the last item known before submission; keep one page in memory.
          for (;;) {
            const messages = page.items.flatMap((item) => item.kind === 'message' ? [item.message] : item.messages);
            const runs = page.items.flatMap((item) => item.kind === 'reply' ? [item.run] : []);
            if (page.active_run) runs.push(page.active_run);
            set((state) => ({ messageQueues: mergeQueueRuntime(state.messageQueues, runs, messages) }));
            const current = get().messageQueues[sessionId]?.submission;
            if (current?.clientId !== submission.clientId) return false;
            if (current.accepted || !page.has_before || page.items.some((item) => item.id === submission.boundary)) break;
            page = await chatApi.getHistory(sessionId, { before: page.before_cursor! });
          }
          update(sessionId, (value) => ({ ...value, submission: null,
            paused: value.submission?.accepted ? value.paused === 'unconfirmed' ? null : value.paused
              : value.items.length ? 'submission' : null }));
        }
        const run = get().messageQueues[sessionId]?.run;
        if (run && !terminal(run.status)) {
          const fresh = await runsApi.getRun(run.run_id);
          get().observeQueueRun(fresh);
          if (get().currentSession?.session_id === sessionId) await get().refreshCurrent();
        }
        update(sessionId, (value) => value.paused === 'unconfirmed' && !value.submission
          ? { ...value, paused: value.run && ['FAILED', 'CANCELLED', 'INTERRUPTED'].includes(value.run.status) ? 'failed' : null } : value);
        return true;
      } catch (error) {
        update(sessionId, (value) => ({ ...value, paused: value.paused ?? 'unconfirmed' }));
        if (get().currentSession?.session_id === sessionId) set({ error: errorText(error) });
        return false;
      }
    },
    resumeMessageQueue: async () => {
      const sessionId = get().currentSession?.session_id;
      if (!sessionId || !(await get().reconcileMessageQueue(sessionId))) return;
      update(sessionId, (queue) => queue.submission || queue.run?.status === 'CANCELLING' ? queue : { ...queue, paused: null });
    },
    dispatchQueuedMessage: async () => {
      const state = get(), sessionId = state.currentSession?.session_id;
      const queue = sessionId ? state.messageQueues[sessionId] : undefined;
      const head = queue?.items[0];
      if (!sessionId || state.queueTarget !== sessionId || !head || queue!.paused || queue!.submission ||
          queue!.editing?.id === head.id || state.sending || state.mutatingHistory || state.historyLoading ||
          state.savingSessionIds.includes(sessionId) || state.resolvingApprovals.length > 0 ||
          state.sessionLoad && state.sessionLoad.status !== 'ready' || state.currentSession?.waiting_run_id ||
          queue!.run && !terminal(queue!.run.status) || state.runs.some((run) => !terminal(run.status))) return;
      await get().sendMessage(head.content, head.attachments, head.id);
    },
  };
};
