import type { RunEventsPage } from '../types/history';
import type { HistoryPruned, Run, RuntimeResponse } from '../types/runs';
import { request } from './http';
import type { ContextDetail } from '../types/context';

export const runsApi = {
  getRun: (runId: string) => request<Run>(`/api/runs/${encodeURIComponent(runId)}`),
  getContext: (runId: string, stepId: string, signal?: AbortSignal) =>
    request<ContextDetail>(`/api/runs/${encodeURIComponent(runId)}/steps/${encodeURIComponent(stepId)}/context`, { signal }),
  deleteRun: (runId: string) => request<HistoryPruned>(`/api/runs/${encodeURIComponent(runId)}`, { method: 'DELETE' }),
  retryRun: (runId: string) => request<RuntimeResponse>(`/api/runs/${encodeURIComponent(runId)}/retry`, { method: 'POST' }),
  listRunEvents: (runId: string, after?: string) => request<RunEventsPage>(`/api/runs/${encodeURIComponent(runId)}/events${after ? `?after=${encodeURIComponent(after)}` : ""}`),
  cancelRun: (runId: string) =>
    request<{ run: Run; cancelled: boolean; reason: string }>(`/api/runs/${encodeURIComponent(runId)}/cancel`, {
      method: 'POST',
    }),
};
