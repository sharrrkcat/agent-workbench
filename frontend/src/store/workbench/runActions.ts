import type { WorkbenchActions } from './state';
import { errorText, mergeRuns, mergeSteps, toolResponseState, pruneHistoryState, runtimeResponseState } from './mergeState';

import { runsApi } from '../../api/runs';
import { toolsApi } from '../../api/tools';

export const createRunActions: WorkbenchActions<'deleteRun' | 'retryRun' | 'cancelRun' | 'resolveApproval' | 'callTool'> = (set, get) => ({
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
    try {
      const response = await runsApi.cancelRun(runId);
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

  callTool: async (name, args) => {
    const session = get().currentSession;
    const epoch = get().sessionEpoch;
    if (!session || get().sending || get().mutatingHistory) return undefined;
    set({ sending: true, error: null });
    try {
      const response = await toolsApi.callTool(name, session.session_id, args);
      if (get().sessionEpoch !== epoch) return undefined;
      set((state) => toolResponseState(state, response));
      return response;
    } catch (error) {
      if (get().currentSession?.session_id === session.session_id && get().sessionEpoch === epoch) set({ error: errorText(error) });
    } finally {
      if (get().sessionEpoch === epoch) set({ sending: false });
    }
    return undefined;
  },
});
