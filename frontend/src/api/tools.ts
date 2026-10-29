import type { HarnessTool, ToolRunResponse } from '../types/tools';
import { request } from './http';

export const toolsApi = {
  listTools: () => request<HarnessTool[]>('/api/tools'),
  resolveToolApproval: (runId: string, decision: 'approve' | 'reject') =>
    request<ToolRunResponse>(`/api/tools/approvals/${encodeURIComponent(runId)}`, {
      method: 'POST',
      body: JSON.stringify({ decision }),
    }),
  getToolRun: (runId: string) => request<ToolRunResponse>(`/api/tools/runs/${encodeURIComponent(runId)}`),
};
