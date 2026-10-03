import { chatApi } from '../../api/chat';
import type { CogitaActions } from './state';
import { errorText } from './mergeState';
import { historyPageState } from './historyWindow';

export const createHistoryActions: CogitaActions<'loadHistory' | 'refreshCurrent' | 'setHistoryAnchor' | 'setHistoryFollowing'> = (set, get) => {
  let requestId = 0;
  let refreshing: { epoch: number; promise: Promise<void>; again: boolean } | null = null;
  return {
    setHistoryAnchor: (cursor) => { if (get().historyAnchor !== cursor) set({ historyAnchor: cursor }); },
    setHistoryFollowing: (following) => { if (get().historyFollowing !== following) set({ historyFollowing: following }); },
    loadHistory: async (direction, cursor) => {
      const session = get().currentSession;
      if (!session || (get().historyLoading && direction !== 'around' && direction !== 'latest')) return;
      const epoch = get().sessionEpoch;
      const request = ++requestId;
      const window = get().historyWindow;
      const position = cursor ?? (direction === 'before' ? window?.before_cursor : window?.after_cursor);
      if (direction !== 'latest' && !position) return;
      set({ historyLoading: true, error: null, ...(direction !== 'latest' ? { historyFollowing: false } : {}) });
      const versions = { messages: get().messageVersion, runs: get().runVersion };
      try {
        const page = await chatApi.getHistory(session.session_id, direction === 'latest' ? {} : { [direction]: position });
        if (get().sessionEpoch !== epoch || get().currentSession?.session_id !== session.session_id || request !== requestId) return;
        if ((direction === 'before' || direction === 'after') && window && page.history_version !== window.history_version) {
          await get().loadHistory('around', get().historyAnchor ?? position!);
          return;
        }
        set((state) => historyPageState(state, page, direction, versions));
      } catch (error) {
        if (get().sessionEpoch === epoch && request === requestId) set({ error: errorText(error) });
      } finally {
        if (get().sessionEpoch === epoch && request === requestId) set({ historyLoading: false });
      }
    },
    refreshCurrent: async () => {
      const initial = get();
      const session = initial.currentSession;
      if (!session || initial.sessionLoad && initial.sessionLoad.status !== 'ready') return;
      if (refreshing?.epoch === initial.sessionEpoch) { refreshing.again = true; return refreshing.promise; }
      const epoch = initial.sessionEpoch;
      const request = requestId;
      const job = { epoch, promise: Promise.resolve(), again: false };
      refreshing = job;
      job.promise = (async () => {
        try {
          do {
            job.again = false;
            const snapshot = get();
            const anchor = snapshot.historyFollowing ? null : snapshot.historyAnchor ?? snapshot.historyWindow?.before_cursor;
            const [fresh, page] = await Promise.all([chatApi.getSession(session.session_id),
              chatApi.getHistory(session.session_id, anchor ? { around: anchor, limit: 100 } : {})]);
            if (get().sessionEpoch !== epoch || get().currentSession?.session_id !== session.session_id || request !== requestId) return;
            set((state) => ({ ...historyPageState(state, page, anchor ? 'around' : 'latest',
                { messages: snapshot.messageVersion, runs: snapshot.runVersion }),
              ...(state.sessionVersion === snapshot.sessionVersion ? { currentSession: fresh,
                sessions: state.sessions.map((s) => s.session_id === fresh.session_id ? fresh : s),
                sessionVersion: state.sessionVersion + 1 } : {}) }));
          } while (job.again);
        } catch (error) {
          if (get().sessionEpoch === epoch) set({ error: errorText(error) });
        } finally {
          if (refreshing === job) refreshing = null;
        }
      })();
      return job.promise;
    },
  };
};
