export type ModelKind = 'llm' | 'embedding' | 'reranker' | 'image_embedding' | 'vision' | 'tts' | 'asr' | 'processor';
export type LocalEngine = 'llama-server' | 'transformers' | 'kokoro' | 'wd14' | 'chatterbox' | 'qwen3tts' | 'siglip2' | 'sentence-transformers' | 'cross-encoder' | 'whisper' | 'dlss5nr';
export type ComponentId = 'dlss5nr';
export type SiglipTower = 'image' | 'text';
export type SiglipTowerInfo = {
  tower: SiglipTower; device: 'cpu' | 'cuda'; device_name: string;
  dtype: 'float16' | 'float32'; output_dtype: 'float32'; dimensions: number;
  model_revision: string; vector_space_id: string;
};
export type SiglipTowerStatus = {
  process_state: 'stopped' | 'starting' | 'ready' | 'failed';
  residency: 'loaded' | 'unloaded'; error_code: string | null; info: SiglipTowerInfo | null;
};
export type SiglipTowers = {
  image: SiglipTowerStatus; text: SiglipTowerStatus; active_tower: SiglipTower | null;
  model_revision: string | null; vector_space_id: string | null; dimensions: number | null;
};
export type SiglipInspection = {
  kind: 'image_embedding'; model_ref: string; model_type: string | null; structure: 'fixres' | 'naflex' | null;
  image: { dimensions: number | null; image_size: number | null; patch_size: number | null };
  text: { dimensions: number | null; hidden_size: number | null; max_position_embeddings: number | null;
    tokenizer_class: string | null; tokenizer_max_length: number | null; do_lower_case: boolean | null;
    add_bos_token: boolean | null; add_eos_token: boolean | null };
  processor: { image_processor_type: string | null; do_resize: boolean | null;
    size: number | Record<string, number> | null; resample: number | null;
    do_rescale: boolean | null; rescale_factor: number | null; do_normalize: boolean | null;
    image_mean: number[] | number | null; image_std: number[] | number | null;
    do_convert_rgb: boolean | null; patch_size: number | null; max_num_patches: number | null };
  diagnostics: { file: string; code: 'missing_config' | 'invalid_config' | 'invalid_field' | 'unknown_structure'; message: string }[];
};

export type VisionParameters = {
  task: 'tags';
  thresholds: { general: number; character: number };
};

export type DirectoryDiagnostic = {
  file: string; message: string; blocking: boolean;
  code: 'missing_directory' | 'missing_file' | 'invalid_config' | 'unsupported_configuration'
    | 'ambiguous_model' | 'ambiguous_projector' | 'incomplete_shards';
};
export type LLMInspection = {
  kind: 'llm'; model_ref: string; engine: 'llama-server' | 'transformers' | null;
  architecture: string | null; main_model_ref: string | null; mmproj_ref: string | null;
  model_files: string[]; diagnostics: DirectoryDiagnostic[];
};
export type TTSInspection = {
  kind: 'tts'; model_ref: string; engine: 'kokoro' | 'chatterbox' | 'qwen3tts' | null;
  architecture: 'kokoro' | 'chatterbox' | 'qwen3tts' | null; diagnostics: DirectoryDiagnostic[];
};
export type VisionInspection = {
  kind: 'vision'; model_ref: string; engine: 'wd14' | null;
  architecture: 'wd14' | null; backbone: string | null; diagnostics: DirectoryDiagnostic[];
};
export type ProcessorInspection = {
  kind: 'processor'; model_ref: string; engine: 'dlss5nr'; task: 'image_processing'; diagnostics: DirectoryDiagnostic[];
};
export type DirectoryInspection = LLMInspection | TTSInspection | VisionInspection | ProcessorInspection;

export type LocalEmbeddingParameters = {
  query_prompt_name: string | null;
  document_prompt_name: string | null;
};

export type TextEmbeddingInspection = {
  kind: 'embedding'; model_ref: string; model_type: string | null;
  modules: { name: string; path: string; type: string }[];
  pooling: { module: string; modes: string[]; include_prompt: boolean | null }[];
  normalize: boolean | null; dimensions: number | null; max_seq_length: number | null;
  similarity: 'cosine' | 'dot' | null; prompts: Record<string, string>;
  query_prompt_name: string | null; document_prompt_name: string | null;
  diagnostics: { file: string; message: string; blocking: boolean;
    code: 'missing_config' | 'invalid_config' | 'invalid_field' | 'unsupported_configuration'
      | 'invalid_prompt' | 'ambiguous_prompt' | 'missing_pipeline' | 'remote_code'
      | 'missing_token_limit' | 'missing_pooling' }[];
};

export type RerankerInspection = {
  kind: 'reranker'; model_ref: string; architecture: 'cross-encoder' | null; model_type: string | null;
  modules: { name: string; path: string; type: string }[];
  scoring: { method: 'sequence_classification' | 'logit_score' | 'dense' | null; activation: string | null };
  max_seq_length: number | null; has_chat_template: boolean; default_prompt_name: string | null;
  diagnostics: { file: string; message: string; blocking: boolean;
    code: 'missing_config' | 'invalid_config' | 'invalid_field' | 'unsupported_configuration'
      | 'remote_code' | 'missing_scoring' | 'missing_template' | 'missing_token_limit' }[];
};

export type ASRInspection = {
  kind: 'asr'; model_ref: string; architecture: 'whisper' | null; processor: string | null;
  sample_rate: number | null; feature_size: number | null; window_seconds: number | null;
  multilingual: boolean | null; languages: string[]; segment_timestamps: boolean;
  diagnostics: { file: string; message: string; blocking: boolean;
    code: 'missing_config' | 'invalid_config' | 'invalid_field' | 'unsupported_configuration' | 'remote_code' }[];
};

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
  execution_options: Record<string, string | number | null>;
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
  towers?: SiglipTowers | null;
  runtime?: {
    engine: LocalEngine;
    version: string;
    install_state: RuntimeInstallState;
    process_state: 'stopped' | 'starting' | 'ready' | 'failed';
    job_id: string | null;
    device_name: string | null;
    gpu_layers_loaded: number | null;
    gpu_layers_total: number | null;
    component: { component_id: ComponentId; version: string; state: RuntimeInstallState;
      job_id: string | null; error_code: string | null } | null;
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
  engines: { engine: LocalEngine; kind: ModelKind; options_schema: Record<string, unknown> }[];
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
  component_id: ComponentId | null;
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

export type RuntimeComponent = RuntimeInstallation & {
  component_id: ComponentId; bundled_version: string; default_profile_id: string | null;
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
