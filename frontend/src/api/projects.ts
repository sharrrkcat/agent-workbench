import type { Project, ProjectInput, ProjectPatch } from '../types/projects';
import type { WorkspaceSession, WorkspaceSessionPatch } from '../types/chat';
import { request } from './http';

const path = (id: string) => `/api/projects/${encodeURIComponent(id)}`;

export const projectsApi = {
  list: () => request<Project[]>('/api/projects'),
  get: (id: string) => request<Project>(path(id)),
  create: (values: ProjectInput) => request<Project>('/api/projects', { method: 'POST', body: JSON.stringify(values) }),
  update: (id: string, values: ProjectPatch) => request<Project>(path(id), { method: 'PATCH', body: JSON.stringify(values) }),
  remove: (id: string) => request<{ deleted: boolean; project_id: string; deleted_session_ids: string[] }>(path(id), { method: 'DELETE' }),
  listSessions: (id: string) => request<WorkspaceSession[]>(path(id) + '/sessions'),
  createSession: (id: string, values: WorkspaceSessionPatch = {}) => request<WorkspaceSession>(path(id) + '/sessions', {
    method: 'POST', body: JSON.stringify(values),
  }),
};
