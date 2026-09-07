import type { WorkbenchActions } from './state';
import { errorText, mergeRuns, mergeSteps, toolResponseState } from './mergeState';

import { runsApi } from '../../api/runs';
import { toolsApi } from '../../api/tools';

export const createRunActions: WorkbenchActions<'cancelRun' | 'resolveApproval' | 'callTool'> = (set, get) => ({
  cancelRun: async (runId) => {
    const sessionId = get().currentSession?.session_id;
    try {
      const response = await runsApi.cancelRun(runId);
      if (get().currentSession?.session_id !== response.run.session_id) return;
      set((state) => ({
        runs: mergeRuns(state.runs, [response.run]),
        stepsByRunId: mergeSteps(state.stepsByRunId, response.run.steps || []),
      }));
      await get().refreshCurrent();
    } catch (error) {
      if (get().currentSession?.session_id === sessionId) set({ error: errorText(error) });
    }
  },

  resolveApproval: async (runId, decision) => {
    if (get().resolvingApprovals.includes(runId)) return;
    const sessionId = get().currentSession?.session_id;
    set((state) => ({ resolvingApprovals: [...state.resolvingApprovals, runId], error: null }));
    try {
      const response = await toolsApi.resolveToolApproval(runId, decision);
      set((state) => toolResponseState(state, response));
    } catch (error) {
      if (get().currentSession?.session_id === sessionId) set({ error: errorText(error) });
    } finally {
      set((state) => ({ resolvingApprovals: state.resolvingApprovals.filter((id) => id !== runId) }));
    }
  },

  callTool: async (name, args) => {
    const session = get().currentSession;
    if (!session || get().sending) return undefined;
    set({ sending: true, error: null });
    try {
      const response = await toolsApi.callTool(name, session.session_id, args);
      set((state) => toolResponseState(state, response));
      return response;
    } catch (error) {
      if (get().currentSession?.session_id === session.session_id) set({ error: errorText(error) });
    } finally {
      set({ sending: false });
    }
    return undefined;
  },
});
