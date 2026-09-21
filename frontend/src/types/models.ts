export type ModelKind = 'llm' | 'embedding' | 'reranker' | 'image_embedding' | 'vision' | 'tts';
export type LocalEngine = 'llama-server' | 'transformers' | 'kokoro' | 'chatterbox' | 'qwen3tts';

export type PresetVoice = {
  id: string; model: string; source: 'preset'; language: string; expires_at: null; available: boolean;
};

export type ModelCapabilities = {
  streaming: boolean;
  tools: boolean;
  vision: boolean;
  json_object: boolean;
  json_schema: boolean;
};

export type LocalModelSource = {
  type: 'local';
  execution_options: Record<string, string | number>;
  lifecycle: { unload: 'manual' | 'after_request' | 'idle'; idle_seconds: number };
};
export type ModelSource = LocalModelSource | { type: 'provider'; provider_profile_id: string };

export type ModelInput = {
  alias: string;
  name: string;
  kind: ModelKind;
  source: ModelSource | null;
  model_ref: string;
  enabled: boolean;
  external_enabled: boolean;
  capabilities: ModelCapabilities;
  parameters: Record<string, unknown>;
};

export type ModelProfile = ModelInput & { id: string; created_at: string; updated_at: string };

export type ExternalConnection = {
  base_url: string;
  api_key?: string;
  timeout_seconds: number;
  concurrency: number;
  queue_size: number;
  queue_timeout_seconds: number;
};

export type ProviderInput = {
  name: string;
  enabled: boolean;
  connection: ExternalConnection;
};

export type ProviderPatch = Partial<Omit<ProviderInput, 'connection'>> & {
  connection?: Partial<ExternalConnection>;
};
export type ProviderProfile = Omit<ProviderInput, 'connection'> & {
  id: string;
  connection: Omit<ExternalConnection, 'api_key'> & { has_api_key: boolean };
  created_at: string;
  updated_at: string;
};

export type ModelSettings = {
  default_model_profile_id: string | null;
  utility_model_profile_id: string | null;
  external_enabled: boolean;
  has_external_api_key: boolean;
  max_request_mb: number;
};

export type ModelStatus = {
  state: 'unknown' | 'ready' | 'unavailable' | 'failed' | 'unloaded';
  residency: 'unknown' | 'loaded' | 'unloaded';
  unload_supported: boolean;
  active: number;
  queued: number;
  error_code: string | null;
  runtime?: {
    engine: LocalEngine;
    version: string;
    install_state: RuntimeInstallState;
    process_state: 'stopped' | 'starting' | 'ready' | 'failed';
    job_id: string | null;
    device_name: string | null;
    gpu_layers_loaded: number | null;
    gpu_layers_total: number | null;
  } | null;
};

export type RuntimeInstallState =
  | 'not_installed'
  | 'installing'
  | 'installed'
  | 'broken'
  | 'unsupported'
  | 'interrupted';

export type RuntimeCatalog = {
  version: string;
  platform: string;
  architecture: string;
  supported: boolean;
  reason: string | null;
  engines: { engine: LocalEngine; kind: 'llm' | 'tts'; options_schema: Record<string, unknown> }[];
};

export type RuntimeInstallation = {
  version: string;
  state: RuntimeInstallState;
  job_id: string | null;
  error_code: string | null;
  updated_at: string;
};

export type RuntimeJob = {
  id: string;
  version: string | null;
  operation: 'install' | 'repair' | 'uninstall' | 'cache_prune' | 'cache_clean';
  result: { before: StorageUsage | null; after: StorageUsage | null } | null;
  state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted';
  stage: string;
  progress_current: number;
  progress_total: number | null;
  error_code: string | null;
  cancel_requested: boolean;
  revision: number;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
};

export type StorageUsage = {
  complete: boolean;
  file_count: number | null;
  logical_bytes: number | null;
  unique_bytes: number | null;
  shared_bytes: number | null;
  exclusive_bytes: number | null;
};

export type StorageGroup = StorageUsage & {
  id: string;
  category: 'runtime' | 'python' | 'cache' | 'staging' | 'processes' | 'other';
  relative_path: string;
  version: string | null;
};

export type RuntimeStorage = {
  scanned_at: string;
  complete: boolean;
  totals: StorageUsage;
  groups: StorageGroup[];
  warnings: { code: string; relative_path: string }[];
  skipped_links: number;
};

export type RuntimeDownloadSettings = {
  http_proxy: string | null;
  pypi_index_url: string | null;
  pytorch_index_url: string | null;
  github_release_proxy_url: string | null;
};

export type LocalRuntimeSettings = { enabled: boolean; download: RuntimeDownloadSettings };
export type LocalRuntimeSettingsPatch = { enabled?: boolean; download?: Partial<RuntimeDownloadSettings> };

export type ModelInventoryItem = {
  kind: ModelKind;
  name: string;
  model_ref: string;
  state: string;
  error_code: string;
};
