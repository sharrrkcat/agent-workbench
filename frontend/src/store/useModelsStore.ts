import { create } from 'zustand';
import { modelsApi } from '../api/models';
import type { ModelProfile, ProviderProfile, ModelSettings, ModelStatus, RuntimeCatalog, RuntimeComponent, RuntimeInstallation, RuntimeJob, RuntimeStorage, LocalRuntimeSettings } from '../types/models';
import type { RuntimeEvent } from '../types/runs';

type ModelsState = {
  profiles: ModelProfile[]; providers: ProviderProfile[]; settings: ModelSettings | null;
  statuses: Record<string, ModelStatus>; loading: boolean; error: string;
  reload: () => Promise<void>;
  setStatus: (id: string, status: ModelStatus) => void;
  localRuntimeSettings: LocalRuntimeSettings | null;
  catalog: RuntimeCatalog | null; installation: RuntimeInstallation | null; components: RuntimeComponent[]; jobs: RuntimeJob[];
  runtimeLoading: boolean; runtimeError: string;
  reloadRuntimes: () => Promise<void>;
  storage: RuntimeStorage | null; storageLoading: boolean; storageError: string;
  reloadStorage: () => Promise<void>;
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
  let componentVersion = 0;
  let storageVersion = 0;
  return {
  profiles: [], providers: [], settings: null, statuses: {}, loading: false, error: '',
  localRuntimeSettings: null, catalog: null, installation: null, components: [], jobs: [], runtimeLoading: false, runtimeError: '',
  storage: null, storageLoading: false, storageError: '',
  reloadStorage: async () => {
    const version = ++storageVersion;
    set({ storageLoading: true, storageError: '' });
    try {
      const storage = await modelsApi.runtimeStorage();
      if (version === storageVersion) set({ storage });
    } catch (error) {
      if (version === storageVersion) set({ storage: null, storageError: error instanceof Error ? error.message : String(error) });
      throw error;
    } finally {
      if (version === storageVersion) set({ storageLoading: false });
    }
  },
  reloadRuntimes: async () => {
    const version = ++runtimeVersion;
    const initialInstallationVersion = installationVersion;
    const initialComponentVersion = componentVersion;
    set({ runtimeLoading: true, runtimeError: '' });
    try {
      const [catalog, installation, jobs, localRuntimeSettings, components] = await Promise.all([modelsApi.runtimeCatalog(), modelsApi.runtimeInstallation(), modelsApi.runtimeJobs(), modelsApi.localRuntimeSettings(), modelsApi.runtimeComponents()]);
      if (version !== runtimeVersion) return;
      set((state) => ({ catalog, localRuntimeSettings, installation: initialInstallationVersion === installationVersion ? installation : state.installation,
        components: initialComponentVersion === componentVersion ? components : state.components,
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
      set({ installation });
    }
    if (event.type === 'runtime_status' && payload.component) {
      const component = payload.component as RuntimeComponent;
      componentVersion++;
      set({ components: [component] });
      if (component.state === 'installed') void get().reload().catch(() => undefined);
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
