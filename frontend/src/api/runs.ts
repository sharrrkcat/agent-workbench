import type { Run, RunEvent } from '../types/runs';
import { request } from './http';

export const runsApi = {
  listRuns: (sessionId: string) => request<Run[]>(`/api/sessions/${encodeURIComponent(sessionId)}/runs`),
  getRun: (runId: string) => request<Run>(`/api/runs/${encodeURIComponent(runId)}`),
  listRunEvents: (runId: string) => request<RunEvent[]>(`/api/runs/${encodeURIComponent(runId)}/events`),
  cancelRun: (runId: string) =>
    request<{ run: Run; cancelled: boolean; reason: string }>(`/api/runs/${encodeURIComponent(runId)}/cancel`, {
      method: 'POST',
    }),
};
