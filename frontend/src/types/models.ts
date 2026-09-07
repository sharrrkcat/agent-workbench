export type ModelKind = 'llm' | 'embedding' | 'reranker' | 'image_embedding' | 'vision';

export type ModelCapabilities = {
  streaming: boolean;
  tools: boolean;
  vision: boolean;
  json_object: boolean;
  json_schema: boolean;
};

export type ModelInput = {
  alias: string;
  name: string;
  kind: ModelKind;
  provider_profile_id: string | null;
  model_ref: string;
  enabled: boolean;
  external_enabled: boolean;
  capabilities: ModelCapabilities;
  parameters: Record<string, unknown>;
  lifecycle: { unload: 'manual' | 'after_request' | 'idle'; idle_seconds: number };
  runtime_id: 'llama-server' | 'python-worker' | null;
  runtime_variant: string | null;
  runtime_options: Record<string, string | number>;
};

export type ModelProfile = ModelInput & { id: string; created_at: string; updated_at: string };

export type ProviderInput = {
  name: string;
  protocol: 'openai_compatible';
  base_url: string;
  api_key?: string;
  timeout_seconds: number;
  concurrency: number;
  queue_size: number;
  queue_timeout_seconds: number;
  enabled: boolean;
};

export type ProviderProfile = Omit<ProviderInput, 'api_key'> & {
  id: string;
  has_api_key: boolean;
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
    runtime_id: string;
    variant: string;
    version: string;
    install_state: RuntimeInstallState;
    process_state: 'stopped' | 'starting' | 'ready' | 'failed';
    job_id: string | null;
  } | null;
};

export type RuntimeInstallState =
  | 'not_installed'
  | 'installing'
  | 'installed'
  | 'broken'
  | 'unsupported'
  | 'interrupted';

export type RuntimeCatalogEntry = {
  runtime_id: 'llama-server' | 'python-worker';
  variant: string;
  version: string;
  platform: string;
  architecture: string;
  supported: boolean;
  reason: string | null;
  kinds: ModelKind[];
  options_schema: Record<string, unknown>;
};

export type RuntimeInstallation = {
  id: string;
  runtime_id: string;
  variant: string;
  version: string;
  state: RuntimeInstallState;
  job_id: string | null;
  error_code: string | null;
  updated_at: string;
};

export type RuntimeJob = {
  id: string;
  runtime_id: string;
  variant: string;
  version: string;
  operation: 'install' | 'uninstall';
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

export type RuntimeDownloadSettings = {
  http_proxy: string | null;
  pypi_index_url: string | null;
  pytorch_index_url: string | null;
  github_release_proxy_url: string | null;
};

export type ModelInventoryItem = {
  kind: ModelKind;
  name: string;
  model_ref: string;
  state: string;
  error_code: string;
};
