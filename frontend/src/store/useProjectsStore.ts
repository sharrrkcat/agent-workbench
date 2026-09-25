import { create } from 'zustand';
import { projectsApi } from '../api/projects';
import type { Project, ProjectInput, ProjectPatch } from '../types/projects';

type ProjectsState = {
  projects: Project[];
  version: number;
  reload: () => Promise<void>;
  load: (id: string) => Promise<Project>;
  save: (values: ProjectInput, id?: string) => Promise<Project>;
  remove: (id: string) => Promise<void>;
};

const upsert = (projects: Project[], project: Project) =>
  [project, ...projects.filter((item) => item.id !== project.id)].sort((a, b) => b.updated_at.localeCompare(a.updated_at));

export const useProjectsStore = create<ProjectsState>((set, get) => ({
  projects: [],
  version: 0,
  reload: async () => {
    const version = get().version;
    const projects = await projectsApi.list();
    if (get().version === version) set({ projects });
  },
  load: async (id) => {
    const version = get().version;
    const project = await projectsApi.get(id);
    if (get().version === version) set((state) => ({ projects: upsert(state.projects, project) }));
    return project;
  },
  save: async (values, id) => {
    const version = get().version;
    const { kind: _kind, ...patch } = values;
    const project = id ? await projectsApi.update(id, patch as ProjectPatch) : await projectsApi.create(values);
    if (!id || get().version === version || get().projects.some((item) => item.id === id))
      set((state) => ({ projects: upsert(state.projects, project), version: state.version + 1 }));
    return project;
  },
  remove: async (id) => {
    await projectsApi.remove(id);
    set((state) => ({ projects: state.projects.filter((project) => project.id !== id), version: state.version + 1 }));
  },
}));
