import type { CogitaActions } from './state';
import { errorText, mergeRuns, mergeSteps, toolResponseState, pruneHistoryState, runtimeResponseState } from './mergeState';

import { runsApi } from '../../api/runs';
import { toolsApi } from '../../api/tools';

export const createRunActions: CogitaActions<'deleteRun' | 'retryRun' | 'cancelRun' | 'resolveApproval'> = (set, get) => ({
  deleteRun: async (runId) => {
    if (get().mutatingHistory) return;
    const epoch = get().sessionEpoch;
    set({ mutatingHistory: true, error: null });
    try {
      const response = await runsApi.deleteRun(runId);
      if (get().sessionEpoch !== epoch) return;
      set((state) => pruneHistoryState(state, response));
      await get().refreshCurrent();
    } catch (error) {
      if (get().sessionEpoch === epoch) set({ error: errorText(error) });
    } finally {
      if (get().sessionEpoch === epoch) set({ mutatingHistory: false });
    }
  },

  retryRun: async (runId) => {
    if (get().mutatingHistory) return;
    const epoch = get().sessionEpoch;
    set({ mutatingHistory: true, error: null });
    try {
      const response = await runsApi.retryRun(runId);
      if (get().sessionEpoch !== epoch) return;
      set((state) => runtimeResponseState(state, response));
      await get().refreshCurrent();
    } catch (error) {
      if (get().sessionEpoch === epoch) set({ error: errorText(error) });
    } finally {
      if (get().sessionEpoch === epoch) set({ mutatingHistory: false });
    }
  },

  cancelRun: async (runId) => {
    const sessionId = get().currentSession?.session_id;
    const epoch = get().sessionEpoch;
    if (sessionId) set((state) => {
      const queue = state.messageQueues[sessionId];
      return queue ? { messageQueues: { ...state.messageQueues, [sessionId]: { ...queue, paused: 'stopped' } } } : {};
    });
    try {
      const response = await runsApi.cancelRun(runId);
      get().observeQueueRun(response.run);
      if (get().currentSession?.session_id !== response.run.session_id || get().sessionEpoch !== epoch || get().deletedRunIds.includes(runId)) return;
      set((state) => ({
        runs: mergeRuns(state.runs, [response.run]),
        stepsByRunId: mergeSteps(state.stepsByRunId, response.run.steps || []),
        runVersion: state.runVersion + 1,
      }));
      await get().refreshCurrent();
    } catch (error) {
      if (get().currentSession?.session_id === sessionId && get().sessionEpoch === epoch) set({ error: errorText(error) });
    }
  },

  resolveApproval: async (runId, decision) => {
    if (get().resolvingApprovals.includes(runId)) return;
    const sessionId = get().currentSession?.session_id;
    const epoch = get().sessionEpoch;
    set((state) => ({ resolvingApprovals: [...state.resolvingApprovals, runId], error: null }));
    try {
      const response = await toolsApi.resolveToolApproval(runId, decision);
      if (get().sessionEpoch === epoch) set((state) => toolResponseState(state, response));
    } catch (error) {
      if (get().currentSession?.session_id === sessionId && get().sessionEpoch === epoch) set({ error: errorText(error) });
    } finally {
      set((state) => ({ resolvingApprovals: state.resolvingApprovals.filter((id) => id !== runId) }));
    }
  },
});
