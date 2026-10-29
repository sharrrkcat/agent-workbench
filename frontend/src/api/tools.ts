import type { HarnessTool, ToolRunResponse, WebToolsSettings, WebToolsSettingsPatch } from '../types/tools';
import { request } from './http';

export const toolsApi = {
  listTools: () => request<HarnessTool[]>('/api/tools'),
  getWebSettings: () => request<WebToolsSettings>('/api/tools/web/settings'),
  patchWebSettings: (values: WebToolsSettingsPatch) => request<WebToolsSettings>('/api/tools/web/settings', {
    method: 'PATCH', body: JSON.stringify(values),
  }),
  resolveToolApproval: (runId: string, decision: 'approve' | 'reject') =>
    request<ToolRunResponse>(`/api/tools/approvals/${encodeURIComponent(runId)}`, {
      method: 'POST',
      body: JSON.stringify({ decision }),
    }),
  getToolRun: (runId: string) => request<ToolRunResponse>(`/api/tools/runs/${encodeURIComponent(runId)}`),
};
