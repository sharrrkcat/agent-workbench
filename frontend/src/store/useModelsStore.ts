import { create } from 'zustand';
import { modelsApi } from '../api/models';
import type { ModelProfile, ProviderProfile, ModelSettings, ModelStatus, RuntimeCatalogEntry, RuntimeInstallation, RuntimeJob } from '../types/models';
import type { RuntimeEvent } from '../types/runs';

type ModelsState = {
  profiles: ModelProfile[]; providers: ProviderProfile[]; settings: ModelSettings | null;
  statuses: Record<string, ModelStatus>; loading: boolean; error: string;
  reload: () => Promise<void>;
  setStatus: (id: string, status: ModelStatus) => void;
  catalog: RuntimeCatalogEntry[]; installations: RuntimeInstallation[]; jobs: RuntimeJob[];
  runtimeLoading: boolean; runtimeError: string;
  reloadRuntimes: () => Promise<void>;
  setJob: (job: RuntimeJob) => void;
  applyModelEvent: (event: RuntimeEvent) => void;
};

export function mergeRuntimeJobs(current: RuntimeJob[], incoming: RuntimeJob[]): RuntimeJob[] {
  const jobs = new Map(current.map((job) => [job.id, job]));
  for (const job of incoming) {
    if (!jobs.has(job.id) || jobs.get(job.id)!.revision < job.revision) jobs.set(job.id, job);
  }
  return [...jobs.values()].sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id)).slice(0, 200);
}

export const useModelsStore = create<ModelsState>((set, get) => {
  let reloadVersion = 0;
  const statusVersions = new Map<string, number>();
  let runtimeVersion = 0;
  let installationVersion = 0;
  return {
  profiles: [], providers: [], settings: null, statuses: {}, loading: false, error: '',
  catalog: [], installations: [], jobs: [], runtimeLoading: false, runtimeError: '',
  reloadRuntimes: async () => {
    const version = ++runtimeVersion;
    const initialInstallationVersion = installationVersion;
    set({ runtimeLoading: true, runtimeError: '' });
    try {
      const [catalog, installations, jobs] = await Promise.all([modelsApi.runtimeCatalog(), modelsApi.runtimeInstallations(), modelsApi.runtimeJobs()]);
      if (version !== runtimeVersion) return;
      set((state) => ({ catalog, installations: initialInstallationVersion === installationVersion ? installations : state.installations,
        jobs: mergeRuntimeJobs(state.jobs, jobs) }));
    } catch (error) {
      if (version === runtimeVersion) set({ runtimeError: error instanceof Error ? error.message : String(error) });
      throw error;
    } finally { if (version === runtimeVersion) set({ runtimeLoading: false }); }
  },
  setJob: (job) => set((state) => ({ jobs: mergeRuntimeJobs(state.jobs, [job]) })),
  applyModelEvent: (event) => {
    const payload = event.payload || {};
    if (event.type === 'model_status' && payload.model_profile_id) get().setStatus(String(payload.model_profile_id), payload.status as ModelStatus);
    if (event.type === 'runtime_job_updated' && payload.job) get().setJob(payload.job as RuntimeJob);
    if (event.type === 'runtime_status' && payload.installation) {
      const installation = payload.installation as RuntimeInstallation;
      installationVersion++;
      set((state) => ({ installations: [...state.installations.filter((item) => item.id !== installation.id), installation] }));
    }
  },
  reload: async () => {
    const version = ++reloadVersion;
    const initialStatusVersions = new Map(statusVersions);
    set({ loading: true, error: '' });
    try {
      const [profiles, providers, settings] = await Promise.all([modelsApi.listModelProfiles(), modelsApi.listProviderProfiles(), modelsApi.getModelSettings()]);
      const statuses = Object.fromEntries(await Promise.all(profiles.map(async (p) => [p.id, await modelsApi.getModelStatus(p.id)])));
      if (version !== reloadVersion) return;
      for (const profile of profiles) {
        if (statusVersions.get(profile.id) !== initialStatusVersions.get(profile.id) && get().statuses[profile.id]) {
          statuses[profile.id] = get().statuses[profile.id];
        }
      }
      set({ profiles, providers, settings, statuses });
    } catch (error) {
      if (version !== reloadVersion) return;
      set({ error: error instanceof Error ? error.message : String(error) });
      throw error;
    } finally { if (version === reloadVersion) set({ loading: false }); }
  },
  setStatus: (id, status) => {
    statusVersions.set(id, (statusVersions.get(id) || 0) + 1);
    set((state) => ({ statuses: { ...state.statuses, [id]: status } }));
  },
  };
});
