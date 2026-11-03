import { create } from 'zustand';
import { modelsApi } from '../api/models';
import type { ModelProfile, ProviderProfile, ModelSettings, ModelStatus, RuntimeCatalog, RuntimeComponent, RuntimeInstallation, RuntimeJob, RuntimeStorage, LocalRuntimeSettings } from '../types/models';
import type { RuntimeEvent } from '../types/runs';

type ModelsState = {
  profiles: ModelProfile[]; providers: ProviderProfile[]; settings: ModelSettings | null;
  statuses: Record<string, ModelStatus>; loading: boolean; error: string;
  reloadProfiles: (force?: boolean) => Promise<void>;
  reloadProviders: (force?: boolean) => Promise<void>;
  reloadSettings: (force?: boolean) => Promise<void>;
  reloadStatuses: (ids: string[], signal?: AbortSignal) => Promise<void>;
  statusErrors: Record<string, string>;
  connectionVersion: number;
  reconnected: () => void;
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
  type Domain = 'profiles' | 'providers' | 'settings';
  const reads = new Map<Domain, { promise: Promise<void>; again: boolean }>();
  const errors: Partial<Record<Domain, string>> = {};
  function read(domain: Domain, fetch: () => Promise<Partial<ModelsState>>, force = false): Promise<void> {
    const pending = reads.get(domain);
    if (pending) { pending.again ||= force; return pending.promise; }
    const job = { promise: Promise.resolve(), again: false };
    reads.set(domain, job); delete errors[domain];
    set({ loading: true, error: Object.values(errors)[0] ?? '' });
    job.promise = (async () => {
      try {
        do {
          job.again = false;
          const value = await fetch();
          if (!job.again) set(value);
        } while (job.again);
      } catch (reason) {
        errors[domain] = reason instanceof Error ? reason.message : String(reason);
        set({ error: Object.values(errors)[0] ?? '' });
        throw reason;
      } finally { reads.delete(domain); set({ loading: reads.size > 0 }); }
    })();
    return job.promise;
  }
  let activeStatuses = 0;
  const statusQueue: (() => void)[] = [];
  const statusReads = new Map<string, { promise: Promise<void>; signal?: AbortSignal }>();
  function drainStatuses() {
    while (activeStatuses < 4 && statusQueue.length) statusQueue.shift()!();
  }
  const statusVersions = new Map<string, number>();
  let runtimeVersion = 0;
  let installationVersion = 0;
  let componentVersion = 0;
  let storageVersion = 0;
  return {
  profiles: [], providers: [], settings: null, statuses: {}, statusErrors: {}, loading: false, error: '',
  connectionVersion: 0, reconnected: () => set((state) => ({ connectionVersion: state.connectionVersion + 1 })),
  localRuntimeSettings: null, catalog: null, installation: null, components: [], jobs: [], runtimeLoading: false, runtimeError: '',
  storage: null, storageLoading: false, storageError: '',
  reloadStorage: async () => {
    const version = ++storageVersion;
    set({ storageLoading: true, storageError: '' });
    try {
      const storage = await modelsApi.runtimeStorage();
      if (version === storageVersion) set({ storage });
    } catch (error) {
      if (version === storageVersion) set({ storageError: error instanceof Error ? error.message : String(error) });
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
      if (component.state === 'installed') {
        get().reconnected();
        void get().reloadProfiles(true).catch(() => undefined);
      }
    }
  },
  reloadProfiles: (force = false) => read('profiles', async () => ({ profiles: await modelsApi.listModelProfiles() }), force),
  reloadProviders: (force = false) => read('providers', async () => ({ providers: await modelsApi.listProviderProfiles() }), force),
  reloadSettings: (force = false) => read('settings', async () => ({ settings: await modelsApi.getModelSettings() }), force),
  reloadStatuses: async (ids, signal) => {
    await Promise.all([...new Set(ids)].map((id) => {
      const existing = statusReads.get(id);
      if (existing) return existing.signal?.aborted ? existing.promise.then(() => get().reloadStatuses([id], signal)) : existing.promise;
      let done!: () => void;
      const promise = new Promise<void>((resolve) => { done = resolve; });
      statusReads.set(id, { promise, signal });
      statusQueue.push(() => {
        if (signal?.aborted) { statusReads.delete(id); done(); return; }
        activeStatuses++;
        const version = statusVersions.get(id);
        set((state) => ({ statusErrors: Object.fromEntries(Object.entries(state.statusErrors).filter(([key]) => key !== id)) }));
        void modelsApi.getModelStatus(id, signal).then((status) => {
          if (!signal?.aborted && statusVersions.get(id) === version) get().setStatus(id, status);
        }).catch((reason) => {
          if (!signal?.aborted && statusVersions.get(id) === version)
            set((state) => ({ statusErrors: { ...state.statusErrors, [id]: reason instanceof Error ? reason.message : String(reason) } }));
        }).finally(() => { activeStatuses--; statusReads.delete(id); done(); drainStatuses(); });
      });
      drainStatuses();
      return promise;
    }));
  },
  setStatus: (id, status) => {
    statusVersions.set(id, (statusVersions.get(id) || 0) + 1);
    set((state) => ({ statuses: { ...state.statuses, [id]: status } }));
  },
  };
});
