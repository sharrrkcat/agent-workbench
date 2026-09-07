import type { HarnessSettings, HarnessTool, ToolRunResponse } from '../types/tools';
import { request } from './http';

export const toolsApi = {
  listTools: () => request<HarnessTool[]>('/api/tools'),
  getToolSettings: () => request<HarnessSettings>('/api/tools/settings'),
  updateToolSettings: (patch: Partial<HarnessSettings>) =>
    request<HarnessSettings>('/api/tools/settings', { method: 'PATCH', body: JSON.stringify(patch) }),
  callTool: (toolName: string, sessionId: string, arguments_: Record<string, unknown>) =>
    request<ToolRunResponse>(`/api/tools/${encodeURIComponent(toolName)}/call`, {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, arguments: arguments_ }),
    }),
  resolveToolApproval: (runId: string, decision: 'approve' | 'reject') =>
    request<ToolRunResponse>(`/api/tools/approvals/${encodeURIComponent(runId)}`, {
      method: 'POST',
      body: JSON.stringify({ decision }),
    }),
  getToolRun: (runId: string) => request<ToolRunResponse>(`/api/tools/runs/${encodeURIComponent(runId)}`),
};
