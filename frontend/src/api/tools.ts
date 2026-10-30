import type { HarnessTool, ToolRunResponse, WebToolsSettings, WebToolsSettingsPatch, WebFilterSettings, WebSubscription } from '../types/tools';
import { request } from './http';

export const toolsApi = {
  listTools: () => request<HarnessTool[]>('/api/tools'),
  getWebSettings: () => request<WebToolsSettings>('/api/tools/web/settings'),
  patchWebSettings: (values: WebToolsSettingsPatch) => request<WebToolsSettings>('/api/tools/web/settings', {
    method: 'PATCH', body: JSON.stringify(values),
  }),
  getWebFilters: () => request<WebFilterSettings>('/api/tools/web/filters'),
  saveWebFilters: (custom_rules: string) => request<WebFilterSettings>('/api/tools/web/filters', {
    method: 'PATCH', body: JSON.stringify({ custom_rules }),
  }),
  addWebSubscription: (values: { name: string; url: string }) => request<WebSubscription>('/api/tools/web/subscriptions', {
    method: 'POST', body: JSON.stringify(values),
  }),
  setWebSubscriptionEnabled: (id: string, enabled: boolean) => request<WebSubscription>(`/api/tools/web/subscriptions/${encodeURIComponent(id)}`, {
    method: 'PATCH', body: JSON.stringify({ enabled }),
  }),
  deleteWebSubscription: (id: string) => request<void>(`/api/tools/web/subscriptions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  refreshWebSubscription: (id: string) => request<WebSubscription>(`/api/tools/web/subscriptions/${encodeURIComponent(id)}/refresh`, { method: 'POST' }),
  resolveToolApproval: (runId: string, decision: 'approve' | 'reject') =>
    request<ToolRunResponse>(`/api/tools/approvals/${encodeURIComponent(runId)}`, {
      method: 'POST',
      body: JSON.stringify({ decision }),
    }),
  getToolRun: (runId: string) => request<ToolRunResponse>(`/api/tools/runs/${encodeURIComponent(runId)}`),
};
