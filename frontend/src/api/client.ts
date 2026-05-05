import type { Agent, AgentConfig, CapabilityConfig, Command, Message, Run, RuntimeResponse, Session } from '../types';

const rawBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
export const API_BASE_URL = rawBaseUrl.replace(/\/$/, '');

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = payload?.error?.message || `Request failed: ${response.status}`;
    const error = new Error(message);
    error.name = payload?.error?.code || 'HTTP_ERROR';
    throw error;
  }
  return payload as T;
}

export const api = {
  listAgents: () => request<Agent[]>('/api/agents'),
  listCommands: () => request<Command[]>('/api/commands'),
  listAgentConfigs: () => request<AgentConfig[]>('/api/agent-configs'),
  getAgentConfig: (agentId: string) => request<AgentConfig>(`/api/agent-configs/${agentId}`),
  updateAgentConfig: (agentId: string, patch: Partial<Pick<AgentConfig, 'enabled' | 'user_config'>>) =>
    request<AgentConfig>(`/api/agent-configs/${agentId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  listCapabilityConfigs: () => request<CapabilityConfig[]>('/api/capability-configs'),
  getCapabilityConfig: (capabilityId: string) => request<CapabilityConfig>(`/api/capability-configs/${capabilityId}`),
  updateCapabilityConfig: (
    capabilityId: string,
    patch: Partial<Pick<CapabilityConfig, 'enabled' | 'user_config'>>,
  ) =>
    request<CapabilityConfig>(`/api/capability-configs/${capabilityId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  listSessions: () => request<Session[]>('/api/sessions'),
  createSession: (title = '', default_agent_id = 'chat') =>
    request<Session>('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({ title, default_agent_id }),
    }),
  getSession: (sessionId: string) => request<Session>(`/api/sessions/${sessionId}`),
  updateSession: (sessionId: string, patch: Partial<Pick<Session, 'title' | 'default_agent_id'>>) =>
    request<Session>(`/api/sessions/${sessionId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  listMessages: (sessionId: string) => request<Message[]>(`/api/sessions/${sessionId}/messages`),
  sendMessage: (sessionId: string, content: string) =>
    request<RuntimeResponse>(`/api/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ content }),
    }),
  invokeAction: (
    sessionId: string,
    payload: { agent_id: string; action_id: string; source_message_id: string; input_text?: string; prefill?: Record<string, unknown> },
  ) =>
    request<RuntimeResponse>(`/api/sessions/${sessionId}/actions`, {
      method: 'POST',
      body: JSON.stringify({ input_text: '', prefill: {}, ...payload }),
    }),
  listRuns: (sessionId: string) => request<Run[]>(`/api/sessions/${sessionId}/runs`),
};

export function createWebSocketUrl(sessionId: string): string {
  const url = new URL(API_BASE_URL);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.pathname = `/api/ws/${sessionId}`;
  return url.toString();
}
