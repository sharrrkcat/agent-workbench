export type AgentAction = {
  id: string;
  label?: string | null;
  description: string;
  instruction?: string | null;
  input_schema?: Record<string, unknown>;
  context_policy?: ContextPolicy | null;
  attach_to?: string | null;
  callable: boolean;
};

export type ContextPolicy = {
  mode: 'none' | 'current_message' | 'recent_messages' | 'last_n' | 'session' | 'selected_message';
  max_messages?: number | null;
  max_chars?: number | null;
  include_system_prompt?: boolean;
  include_attachments?: 'none' | 'explicit';
  include_last_agent_message?: boolean;
  include_original_user_message?: boolean;
};

export type ModelLifecyclePolicy = {
  load: 'on_demand';
  unload: 'never' | 'after_run' | 'manual';
  unload_failure: 'ignore' | 'warn' | 'fail';
};

export type AvatarType = 'image' | 'emoji' | 'text' | 'initials';

export type Agent = {
  id: string;
  name: string;
  type: 'prompt' | 'script';
  description: string;
  avatar?: string | null;
  avatar_type?: AvatarType;
  avatar_url?: string | null;
  resolved_display?: ResolvedAgentDisplay;
  entry?: string | null;
  actions: AgentAction[];
  model?: Record<string, unknown> | null;
  llm?: AgentLlmConfig | null;
  context_policy?: ContextPolicy;
  model_lifecycle?: ModelLifecyclePolicy;
  resolved_runtime?: AgentResolvedRuntime;
  capabilities?: string[];
  enabled: boolean;
};

export type AgentLlmConfig = {
  profile?: string | null;
  allow_session_override?: boolean;
  temperature?: number | null;
  top_p?: number | null;
  top_k?: number | null;
  max_tokens?: number | null;
};

export type Command = {
  name: string;
  capability_id: string;
  method: string;
  description: string;
  safe: boolean;
  confirm?: string | null;
  argument_suggestions?: CommandArgumentSuggestion[];
  enabled: boolean;
  capability_enabled: boolean;
};

export type CommandArgumentSuggestion = {
  value: string;
  label?: string | null;
  description?: string | null;
  next_suggestions?: CommandArgumentNextSuggestions | null;
};

export type CommandArgumentNextSuggestions = {
  provider: 'pet_ids';
};

export type CommandArgumentSuggestionsRequest = {
  command: string;
  args: string[];
  prefix: string;
  session_id?: string | null;
};

export type CommandArgumentSuggestionsResponse = {
  suggestions: CommandArgumentDynamicSuggestion[];
};

export type CommandArgumentDynamicSuggestion = {
  value: string;
  label?: string | null;
  description?: string | null;
};

export type ManifestSummary = {
  id: string;
  name: string;
  type?: string;
  description: string;
  avatar?: string | null;
  avatar_type?: AvatarType;
  avatar_url?: string | null;
  capabilities?: string[];
};

export type AgentDisplayOverrides = {
  name?: string;
  description?: string;
  avatar?: string;
};

export type AgentRuntimeOverrides = {
  llm_profile_id?: string | null;
  llm_profile_key?: string | null;
  allow_session_override?: boolean;
  prompt?: string;
  knowledge_context_mode?: 'use_default' | 'enabled' | 'disabled';
  knowledge_context_effective_mode?: 'enabled' | 'disabled';
  knowledge_context_default_effective_mode?: 'enabled' | 'disabled';
  intent_routing_mode?: 'use_default' | 'enabled' | 'disabled';
  intent_routing_effective_mode?: 'enabled' | 'disabled';
  intent_routing_effective_reason?: string;
  intent_routing_aliases_text?: string;
  intent_routing_examples_text?: string;
  context_policy?: ContextPolicy;
  model_lifecycle?: ModelLifecyclePolicy;
  timeout_seconds?: number;
};

export type ResolvedAgentDisplay = Required<AgentDisplayOverrides> & {
  avatar_type?: AvatarType;
  avatar_url?: string | null;
};

export type AgentResolvedRuntime = AgentRuntimeOverrides & {
  llm_profile_name?: string | null;
  llm_profile_label?: string | null;
  llm_profile_model_id?: string | null;
  llm_profile_source?: string | null;
  llm_profile_status?: 'default' | 'enabled' | 'disabled' | 'missing' | string;
};

export type AgentResolvedSettings = {
  display: ResolvedAgentDisplay;
  runtime: AgentResolvedRuntime;
  sections: { id: string; label: string; capability_id?: string }[];
  field_sources: Record<string, 'default' | 'manifest' | 'override' | string>;
  config?: Record<string, unknown>;
};

export type ConfigFieldSchema = {
  name: string;
  type: 'string' | 'text' | 'integer' | 'float' | 'boolean' | 'enum' | 'json';
  label: string;
  required: boolean;
  default: unknown;
  description: string;
  options: string[];
  secret: boolean;
};

export type AgentConfig = {
  agent_id: string;
  enabled: boolean;
  display?: AgentDisplayOverrides;
  runtime?: AgentRuntimeOverrides;
  user_config: Record<string, unknown>;
  resolved_config: Record<string, unknown>;
  overrides?: {
    display: AgentDisplayOverrides;
    runtime: AgentRuntimeOverrides;
    user_config: Record<string, unknown>;
  };
  manifest?: {
    name: string;
    description: string;
    avatar?: string | null;
    capabilities?: string[];
    llm?: AgentLlmConfig | null;
    prompt?: string | null;
    context_policy?: ContextPolicy;
    model_lifecycle?: ModelLifecyclePolicy;
    timeout_seconds?: number | null;
  };
  resolved?: AgentResolvedSettings;
  field_sources?: Record<string, 'default' | 'manifest' | 'override' | string>;
  config_schema: ConfigFieldSchema[];
  manifest_summary: ManifestSummary;
  created_at: string;
  updated_at: string;
};

export type CapabilityPermissionHints = {
  filesystem?: { read?: boolean };
  network?: { http?: boolean };
};

export type CapabilityConfig = {
  capability_id: string;
  enabled: boolean;
  user_config: Record<string, unknown>;
  resolved_config: Record<string, unknown>;
  config_schema: ConfigFieldSchema[];
  manifest_summary: ManifestSummary & { commands?: Command[]; permissions?: CapabilityPermissionHints };
  created_at: string;
  updated_at: string;
};

export type LlmTestResult = {
  success: boolean;
  message: string;
  base_url: string;
  models?: string[];
  error_code?: string;
  warnings?: string[];
  backend?: Record<string, unknown>;
  models_root?: string;
};

export type WebSearchDiagnosticResultItem = {
  title: string;
  url: string;
  domain: string;
  snippet: string;
  rank?: number;
  published_at?: string | null;
  source?: string;
};

export type WebSearchTestResult = {
  ok: boolean;
  provider: string;
  base_url: string;
  query: string;
  elapsed_ms: number;
  result_count: number;
  first_result: WebSearchDiagnosticResultItem | null;
  sample_results: WebSearchDiagnosticResultItem[];
  warnings: string[];
  diagnostics?: WebSearchDiagnostics;
  error_code?: string;
  error_message?: string;
};

export type WebSearchDiagnostics = {
  raw_result_count?: number;
  normalized_count?: number;
  filtered_count?: number;
  blocked_count?: number;
  allowlist_excluded_count?: number;
  deduped_count?: number;
  final_count?: number;
  filters_applied?: Record<string, boolean>;
  warnings?: string[];
};

export type LlmProfile = {
  id: string;
  alias: string;
  name: string;
  provider_profile_id?: string | null;
  provider: 'openai_compatible' | 'lm_studio' | 'llama_cpp' | 'custom' | 'ollama' | 'internal_transformers' | 'internal_llama_cpp';
  base_url: string;
  api_key: string;
  api_key_set?: boolean;
  model_id: string;
  enabled: boolean;
  temperature?: number | null;
  top_p?: number | null;
  top_k?: number | null;
  max_tokens?: number | null;
  timeout?: number | null;
  supports_vision: boolean;
  supports_tools: boolean;
  supports_reasoning: boolean;
  supports_streaming: boolean;
  supports_json_mode: boolean;
  notes?: string | null;
  created_at: string;
  updated_at: string;
};

export type LlmProviderModel = {
  id: string;
  model_ref?: string;
  name?: string | null;
  type?: 'llm' | 'embedding' | 'unknown' | string;
  display_name?: string | null;
  kind?: 'llm' | 'embedding' | 'reranker' | string;
  source?: 'internal' | string;
  backend?: string;
  relative_path?: string;
  loaded?: boolean | null;
  loaded_instance_ids?: string[];
  capabilities?: {
    vision?: boolean;
    tools?: boolean;
    reasoning?: boolean;
    streaming?: boolean;
    json_mode?: boolean;
  } | null;
  raw?: Record<string, unknown>;
};

export type LlmProviderStatusCode =
  | 'READY'
  | 'PROVIDER_UNREACHABLE'
  | 'MODEL_NOT_AVAILABLE'
  | 'MODEL_NOT_LOADED'
  | 'MODEL_MISMATCH'
  | 'MODEL_STATUS_UNKNOWN'
  | 'UNSUPPORTED'
  | 'UNLOADING'
  | 'UNLOAD_FAILED'
  | 'MODEL_UNLOAD_FAILED';

export type LlmProviderStatusModel = {
  id: string;
  model_ref?: string;
  name?: string | null;
  type?: 'llm' | 'embedding' | 'unknown' | string;
  display_name?: string | null;
  kind?: 'llm' | 'embedding' | 'reranker' | string;
  source?: 'internal' | string;
  backend?: string;
  relative_path?: string;
  available?: boolean | null;
  loaded?: boolean | null;
  status?: LlmProviderStatusCode | string;
  actual_model_id?: string | null;
  loaded_instance_ids?: string[];
  capabilities?: Record<string, boolean>;
  raw?: Record<string, unknown>;
};

export type LlmProviderStatus = {
  provider_profile_id: string;
  provider_profile_name: string;
  provider: string;
  reachable: boolean;
  status: LlmProviderStatusCode | string;
  mode: string;
  checked_at: string;
  models: LlmProviderStatusModel[];
  warnings: string[];
  backend?: Record<string, unknown>;
  models_root?: string;
  runtime_settings?: {
    local_runtime_device?: 'auto' | 'cpu' | 'cuda' | 'mps' | string;
    llama_cpp_gpu_layers?: number;
    warnings?: string[];
  };
  error?: { code?: string; message?: string; raw?: string };
};

export type LlmProviderStatusRefreshResponse = {
  providers: LlmProviderStatus[];
};

export type LlmProviderProfile = {
  id: string;
  name: string;
  provider: 'openai_compatible' | 'lm_studio' | 'llama_cpp' | 'custom' | 'ollama' | 'internal_transformers' | 'internal_llama_cpp';
  base_url: string;
  api_key: string;
  api_key_set?: boolean;
  timeout_seconds?: number | null;
  enabled: boolean;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type LlmProfileInput = Partial<
  Pick<
    LlmProfile,
    | 'alias'
    | 'name'
    | 'provider_profile_id'
    | 'provider'
    | 'base_url'
    | 'api_key'
    | 'model_id'
    | 'enabled'
    | 'temperature'
    | 'top_p'
    | 'top_k'
    | 'max_tokens'
    | 'timeout'
    | 'supports_vision'
    | 'supports_tools'
    | 'supports_reasoning'
    | 'supports_streaming'
    | 'supports_json_mode'
    | 'notes'
  >
>;

export type LlmProviderProfileInput = Partial<
  Pick<LlmProviderProfile, 'name' | 'provider' | 'base_url' | 'api_key' | 'timeout_seconds' | 'enabled' | 'metadata'>
>;

export type LlmDefaults = {
  default_model_profile_id: string | null;
};

export type KnowledgeSettingsCategory = 'defaults' | 'embedding_models' | 'knowledge_bases';
export type WorldbookSettingsCategory = 'defaults' | 'worldbooks';

export type KnowledgeBackendStatus = {
  sentence_transformers_available: boolean;
  torch_available: boolean;
  transformers_available?: boolean;
  cuda_available?: boolean;
  available?: boolean;
};

export type KnowledgeModelScan = {
  models_root: string;
  embedding_models: { model_path: string; name: string; exists: boolean }[];
  reranker_models: { model_path: string; name: string; exists: boolean }[];
  backend: KnowledgeBackendStatus;
};

export type KnowledgeSettings = {
  id: number;
  models_root: string;
  local_model_device: 'auto' | 'cpu' | 'cuda';
  embedding_batch_size: number;
  embedding_timeout_seconds: number;
  unload_embedding_model_after_use: boolean;
  reranker_enabled: boolean;
  reranker_profile_id?: string | null;
  reranker_model_path: string | null;
  reranker_batch_size: number;
  reranker_timeout_seconds: number;
  reranker_candidate_limit: number;
  unload_reranker_model_after_use: boolean;
  hybrid_search_enabled: boolean;
  default_vector_candidate_k: number;
  default_keyword_candidate_k: number;
  default_final_top_k: number;
  default_max_context_chars: number;
  default_min_score: number | null;
  min_score_threshold: number | null;
  retrieval_max_chunks_per_source: number | null;
  retrieval_max_chunks_per_knowledge_base: number | null;
  query_expansion_enabled: boolean;
  query_expansion_max_variants: number;
  query_expansion_prompt: string;
  rrf_k: number;
  default_chunk_size: number;
  default_chunk_overlap: number;
  default_chunk_profile?: 'plain_text' | 'markdown_document' | 'markdown_collection' | 'markdown_auto' | null;
  max_source_size_bytes: number;
  max_chunks_per_source: number;
  max_total_index_chars_per_source: number;
  knowledge_context_instruction: string;
  knowledge_context_snippet_template: string;
};

export type EmbeddingModelProfile = {
  id: string;
  name: string;
  alias: string;
  model_path: string;
  provider_profile_id?: string | null;
  provider_model_id: string;
  dimension?: number | null;
  normalize: boolean;
  document_instruction: string;
  query_instruction: string;
  enabled: boolean;
  notes: string;
  created_at: string;
  updated_at: string;
};

export type EmbeddingModelProfileInput = Partial<
  Pick<
    EmbeddingModelProfile,
    | 'name'
    | 'alias'
    | 'model_path'
    | 'provider_profile_id'
    | 'provider_model_id'
    | 'dimension'
    | 'normalize'
    | 'document_instruction'
    | 'query_instruction'
    | 'enabled'
    | 'notes'
  >
>;

export type RerankerModelProfile = {
  id: string;
  name: string;
  alias: string;
  provider_profile_id: string;
  provider_model_id: string;
  enabled: boolean;
  notes: string;
  created_at: string;
  updated_at: string;
};

export type RerankerModelProfileInput = Partial<
  Pick<
    RerankerModelProfile,
    | 'name'
    | 'alias'
    | 'provider_profile_id'
    | 'provider_model_id'
    | 'enabled'
    | 'notes'
  >
>;

export type KnowledgeBase = {
  id: string;
  name: string;
  description: string;
  aliases_text: string;
  embedding_model_profile_id: string;
  embedding_model_profile_name?: string | null;
  embedding_model_profile_alias?: string | null;
  embedding_model_profile_model_path?: string | null;
  embedding_model_profile_dimension?: number | null;
  enabled: boolean;
  index_status: 'empty' | 'ready' | 'indexing' | 'failed' | 'needs_reindex' | string;
  index_error?: string | null;
  chunk_size_override?: number | null;
  chunk_overlap_override?: number | null;
  vector_candidate_k_override?: number | null;
  keyword_candidate_k_override?: number | null;
  final_top_k_override?: number | null;
  max_context_chars_override?: number | null;
  default_chunk_profile?: 'plain_text' | 'markdown_document' | 'markdown_collection' | 'markdown_auto' | null;
  created_at: string;
  updated_at: string;
};

export type KnowledgeBaseInput = Partial<
  Pick<
    KnowledgeBase,
    | 'name'
    | 'description'
    | 'aliases_text'
    | 'embedding_model_profile_id'
    | 'enabled'
    | 'chunk_size_override'
    | 'chunk_overlap_override'
    | 'vector_candidate_k_override'
    | 'keyword_candidate_k_override'
    | 'final_top_k_override'
    | 'max_context_chars_override'
    | 'default_chunk_profile'
  >
>;

export type SessionKnowledgeBinding = {
  id?: number | null;
  session_id: string;
  knowledge_base_id: string;
  enabled: boolean;
  sort_order: number;
  created_at: string;
  knowledge_base?: KnowledgeBase | null;
};

export type KnowledgeSource = {
  id: string;
  knowledge_base_id: string;
  origin_id?: string | null;
  source_type: 'pasted_text' | 'attachment_text' | 'origin_file' | string;
  uri: string;
  title: string;
  relative_path?: string;
  virtual_path?: string;
  folder_path?: string;
  file_name?: string;
  extension?: string;
  path_depth?: number;
  file_status?: 'ready' | 'new' | 'changed' | 'missing' | 'failed' | string;
  source_mtime?: string | null;
  source_size_bytes?: number;
  mime_type?: string | null;
  size_bytes: number;
  content_hash: string;
  indexed_at?: string | null;
  status: 'pending' | 'indexing' | 'indexed' | 'needs_reindex' | 'failed' | 'deleted' | string;
  error?: string | null;
  metadata: Record<string, unknown>;
  chunks: number;
  embedding_model_profile_id?: string | null;
  embedding_dimension?: number | null;
  chunk_profile_requested?: string | null;
  chunk_profile_effective?: string | null;
  chunk_profile_confidence?: number | null;
  profile_source?: string | null;
  entity_level?: number | null;
  title_source?: string | null;
  type_source?: string | null;
  created_at: string;
  updated_at: string;
};

export type KnowledgeOrigin = {
  id: string;
  knowledge_base_id: string;
  name: string;
  slug: string;
  root_path: string;
  include_globs: string;
  exclude_globs: string;
  default_chunk_profile?: 'plain_text' | 'markdown_document' | 'markdown_collection' | 'markdown_auto' | null;
  last_scan_at?: string | null;
  last_import_at?: string | null;
  status: string;
  error?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type KnowledgeOriginInput = Partial<Pick<KnowledgeOrigin, 'name' | 'slug' | 'include_globs' | 'exclude_globs' | 'default_chunk_profile' | 'status' | 'metadata'>>;

export type KnowledgeOriginFolderSuggestion = {
  name: string;
  path: string;
};

export type KnowledgeOriginFolderSuggestionsResponse = {
  prefix: string;
  folders: KnowledgeOriginFolderSuggestion[];
};

export type KnowledgeOriginScanSummary = {
  origin_id: string;
  new_count: number;
  changed_count: number;
  missing_count: number;
  unchanged_count: number;
  failed_count: number;
  warnings: string[];
};

export type KnowledgeOriginImportSummary = KnowledgeOriginScanSummary & {
  imported_count: number;
  skipped_count: number;
  sources: KnowledgeSourceIndexResult[];
};

export type KnowledgeSourceIndexResult = {
  source_id: string;
  status: string;
  chunks: number;
  embedding_model_profile_id?: string | null;
  embedding_dimension?: number | null;
  indexed_at?: string | null;
  error?: string | null;
  skipped?: boolean;
};

export type KnowledgeSourcePreview = {
  source_id: string;
  title: string;
  source_type: 'pasted_text' | 'attachment_text' | string;
  preview: string;
  truncated: boolean;
  size_bytes: number;
};

export type KnowledgeSourceChunk = {
  chunk_id: string;
  chunk_index: number;
  heading_path: string;
  char_start: number;
  char_end: number;
  content: string;
  content_preview: string;
  truncated?: boolean;
  embedding_dimension?: number | null;
  metadata: Record<string, unknown>;
};

export type KnowledgeSourceChunksResponse = {
  source_id: string;
  chunks: KnowledgeSourceChunk[];
};

export type KnowledgeSearchResult = {
  rank: number;
  chunk_id: string;
  knowledge_base_id: string;
  source_id: string;
  title: string;
  heading_path: string;
  content: string;
  truncated: boolean;
  vector_rank?: number | null;
  vector_score?: number | null;
  keyword_rank?: number | null;
  keyword_score?: number | null;
  rrf_score: number;
  rerank_score?: number | null;
};

export type KnowledgeSearchResponse = {
  query: string;
  results: KnowledgeSearchResult[];
  debug?: {
    embedding_groups: { embedding_model_profile_id: string; knowledge_base_ids: string[]; candidate_count: number }[];
    keyword_candidate_count: number;
    merged_candidate_count: number;
    reranker_used: boolean;
    reranker_failed: boolean;
    query_expansion_enabled?: boolean;
    query_expansion_used?: boolean;
    expanded_query_count?: number;
    expanded_queries?: string[];
    expansion_failed?: boolean;
    before_filter_count?: number;
    min_score_filtered_count?: number;
    per_source_filtered_count?: number;
    per_kb_filtered_count?: number;
    final_result_count?: number;
    warnings: string[];
  };
  context_preview?: string;
};

export type KnowledgeChunk = {
  chunk_id: string;
  knowledge_base_id: string;
  knowledge_base_name: string;
  source_id: string;
  source_title: string;
  heading_path: string;
  content: string;
  chunk_index: number;
  metadata?: Record<string, unknown> & {
    local_runtime_device?: 'auto' | 'cpu' | 'cuda' | 'mps' | string;
    llama_cpp_gpu_layers?: number;
  };
};

export type WorldbookSettings = {
  id: number;
  worldbook_enabled_for_prompt_agents: boolean;
  worldbook_enabled_for_script_agents: boolean;
  worldbook_max_entries_per_call: number;
  worldbook_max_context_chars: number;
  worldbook_regex_case_insensitive: boolean;
  worldbook_recursion_depth: number;
  worldbook_case_sensitive: boolean;
  worldbook_whole_words: boolean;
};

export type Worldbook = {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  entry_count?: number;
  active_binding_count?: number;
};

export type WorldbookInput = Partial<Pick<Worldbook, 'name' | 'description' | 'enabled'>>;

export type WorldbookEntry = {
  id: string;
  worldbook_id: string;
  name: string;
  keywords_text: string;
  content: string;
  activation_mode: 'always' | 'keyword';
  enabled: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
};

export type WorldbookEntryInput = Partial<Pick<WorldbookEntry, 'name' | 'keywords_text' | 'content' | 'activation_mode' | 'enabled' | 'sort_order'>>;

export type SessionWorldbookBinding = {
  id: string;
  session_id: string;
  worldbook_id: string;
  enabled: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
  worldbook?: Worldbook | null;
};

export type SessionWorldbooksResponse = {
  session_id: string;
  enabled_worldbooks: SessionWorldbookBinding[];
  available_worldbooks: Worldbook[];
  warnings?: string[];
};

export type WorldbookMatchResult = {
  worldbook_id: string;
  worldbook_name: string;
  entry_id: string;
  entry_name: string;
  activation_mode: 'always' | 'keyword';
  matched_keywords: string[];
  matched_by_recursion?: boolean;
  recursion_depth?: number;
  sort_order: number;
  content_preview: string;
};

export type WorldbookMatchTestResponse = {
  matched_count: number;
  included_count: number;
  truncated: boolean;
  recursion_depth?: number;
  recursion_rounds_used?: number;
  case_sensitive?: boolean;
  whole_words?: boolean;
  warnings: { code: string; message: string; [key: string]: unknown }[];
  results: WorldbookMatchResult[];
};

export type PetPosition = {
  mode: 'default' | string;
  x: number | null;
  y: number | null;
};

export type PetBubbleTexts = {
  idle: string;
  waiting: string;
  done: string;
  failed: string;
  cancelled: string;
  interrupted: string;
  wake: string;
  tuck: string;
  status: string;
  select: string;
  reload: string;
  no_pet: string;
  import_success: string;
  import_failed: string;
  delete_success: string;
  delete_failed: string;
};

export type PetCommandTexts = {
  wake: string;
  tuck: string;
  select: string;
  status: string;
  reload: string;
  no_pet: string;
  select_missing: string;
};

export type PetSettings = {
  pet_enabled: boolean;
  default_pet_id: string;
  pet_scale: number;
  show_status_bubble: boolean;
  bubble_offset_x: number;
  bubble_offset_y: number;
  jump_on_hover: boolean;
  running_prefix: string;
  position: PetPosition;
  bubble_texts: PetBubbleTexts;
  command_texts: PetCommandTexts;
};

export type PetItem = {
  id: string;
  display_name?: string | null;
  description?: string | null;
  source: string;
  valid: boolean;
  status: string;
  errors: string[];
  can_delete: boolean;
  is_builtin: boolean;
  spritesheet_url?: string | null;
};

export type PetSettingsResponse = {
  settings: PetSettings;
};

export type PetListResponse = {
  pets: PetItem[];
};

export type PetImportResponse = {
  pet: PetItem;
  pets: PetItem[];
  selected: boolean;
  warnings: string[];
  settings?: PetSettings;
};

export type LlmResolvedConfig = {
  source?: string | null;
  profile_id?: string | null;
  profile_alias?: string | null;
  profile_key?: string | null;
  profile_name?: string | null;
  provider_profile_id?: string | null;
  provider_profile_name?: string | null;
  provider?: string | null;
  base_url: string;
  model: string;
  model_id?: string;
  timeout?: number | null;
  api_key_set: boolean;
  temperature?: number | null;
  top_p?: number | null;
  top_k?: number | null;
  max_tokens?: number | null;
  supports_vision?: boolean;
  supports_tools?: boolean;
  supports_reasoning?: boolean;
  supports_streaming?: boolean;
  supports_json_mode?: boolean;
  allow_session_override?: boolean;
  sources?: Record<string, string>;
};

export type ContextMode = 'single_assistant' | 'group_transcript';

export type Session = {
  session_id: string;
  title: string;
  default_agent_id: string;
  context_mode?: ContextMode;
  waiting_run_id?: string | null;
  llm_profile_id?: string | null;
  last_announced_llm_profile_id?: string | null;
  title_generation_state?: 'pending' | 'done' | 'skipped' | 'failed' | 'manual';
  title_generation_metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type AvailableAction = {
  agent_id: string;
  action_id: string;
  label: string;
  source_message_id: string;
  prefill: Record<string, unknown>;
};

export type ActionFormField = {
  name: string;
  type: 'text' | 'textarea' | 'integer' | 'float' | 'boolean' | 'enum' | 'json';
  label?: string | null;
  description?: string | null;
  help?: string | null;
  required?: boolean;
  value?: unknown;
  default?: unknown;
  placeholder?: string | null;
  minimum?: number | null;
  maximum?: number | null;
  min_length?: number | null;
  max_length?: number | null;
  step?: number | null;
  options?: { value: string | number | boolean; label?: string | null }[];
  ui?: {
    section?: string | null;
    span?: number | null;
  } | null;
};

export type ActionFormSection = {
  key: string;
  title?: string | null;
};

export type ActionFormBlock = {
  type: 'action_form';
  form_id: string;
  title: string;
  description?: string | null;
  ui?: {
    default_collapsed?: boolean | null;
    collapsed?: boolean | null;
    collapse_on_success?: boolean | null;
    collapsed_message?: string | null;
  } | null;
  fields: ActionFormField[];
  sections?: ActionFormSection[] | null;
  submit: {
    label?: string | null;
    agent_id?: string | null;
    action_id: string;
    message?: string | null;
    visibility?: 'message' | 'silent' | null;
    success_message?: string | null;
    failure_message?: string | null;
  };
};

export type CommandButtonsBlock = {
  type: 'command_buttons';
  buttons: { label: string; message: string }[];
};

export type ImagePayload = {
  url: string;
  alt?: string | null;
  title?: string | null;
  caption?: string | null;
};

export type ImageAttachment = {
  id: string;
  type: 'image';
  mime_type: 'image/png' | 'image/jpeg' | 'image/webp' | 'image/gif' | 'image/svg+xml';
  name: string;
  size: number;
  data_url?: string;
  uri?: string;
  created_at?: string;
  width?: number;
  height?: number;
};

export type FileAttachment = {
  id: string;
  type: 'file';
  mime_type: string;
  name: string;
  size: number;
  data_url?: string;
  uri?: string;
  created_at?: string;
};

export type AudioAttachment = {
  id: string;
  type: 'audio';
  mime_type: string;
  name: string;
  size: number;
  uri?: string;
  url?: string;
  created_at?: string;
};

export type VideoAttachment = {
  id: string;
  type: 'video';
  mime_type: string;
  name: string;
  size: number;
  uri?: string;
  url?: string;
  created_at?: string;
};

export type Attachment = ImageAttachment | FileAttachment | AudioAttachment | VideoAttachment;

export type FileContentPayload = {
  filename?: string | null;
  language?: string | null;
  mime_type?: string | null;
  content: string;
  size?: number | null;
  truncated?: boolean;
  path?: string | null;
};

export type TextMessagePart = {
  id: string;
  type: 'text';
  format: 'plain' | 'markdown';
  text: string;
};

export type JsonMessagePart = {
  id: string;
  type: 'json';
  data: unknown;
};

export type FileMessagePart = {
  id: string;
  type: 'file';
  mode: 'inline_text' | 'attachment_ref';
  content?: string | null;
  attachment_id?: string | null;
  url?: string | null;
  filename?: string | null;
  language?: string | null;
  mime_type?: string | null;
  size?: number | null;
  truncated?: boolean;
  path?: string | null;
};

export type ImageMessagePart = {
  id: string;
  type: 'image';
  url?: string | null;
  attachment_id?: string | null;
  alt?: string | null;
  title?: string | null;
  caption?: string | null;
  mime_type?: string | null;
};

export type AttachmentAudioMessagePart = {
  id: string;
  type: 'audio';
  source: 'attachment';
  attachment_id: string;
  url: string;
  mime_type: string;
  filename?: string | null;
  title?: string | null;
  duration_ms?: number | null;
  size_bytes?: number | null;
};

export type UrlAudioMessagePart = {
  id: string;
  type: 'audio';
  source: 'url';
  url: string;
  mime_type: string;
  filename?: string | null;
  title?: string | null;
  duration_ms?: number | null;
  size_bytes?: number | null;
};

export type AudioMessagePart = AttachmentAudioMessagePart | UrlAudioMessagePart;

export type AttachmentVideoMessagePart = {
  id: string;
  type: 'video';
  source: 'attachment';
  attachment_id: string;
  url: string;
  mime_type: string;
  filename?: string | null;
  title?: string | null;
  size_bytes?: number | null;
  duration_ms?: number | null;
  width?: number | null;
  height?: number | null;
  poster_url?: string | null;
};

export type UrlVideoMessagePart = {
  id: string;
  type: 'video';
  source: 'url';
  url: string;
  mime_type: string;
  filename?: string | null;
  title?: string | null;
  size_bytes?: number | null;
  duration_ms?: number | null;
  width?: number | null;
  height?: number | null;
  poster_url?: string | null;
};

export type VideoMessagePart = AttachmentVideoMessagePart | UrlVideoMessagePart;

export type MediaGroupMessagePart = {
  id: string;
  type: 'media_group';
  layout: 'gallery';
  items: ({ type: 'image' } & Omit<ImageMessagePart, 'id'>)[];
};

export type FormMessagePart = Omit<ActionFormBlock, 'type'> & {
  id: string;
  type: 'form';
};

export type CommandButtonsMessagePart = {
  id: string;
  type: 'command_buttons';
  buttons: { label: string; message: string }[];
};

export type NoticeMessagePart = {
  id: string;
  type: 'notice';
  level: 'info' | 'warning' | 'success';
  text: string;
};

export type ErrorMessagePart = {
  id: string;
  type: 'error';
  message: string;
  code?: string | null;
};

export type MessagePart =
  | TextMessagePart
  | JsonMessagePart
  | FileMessagePart
  | ImageMessagePart
  | AudioMessagePart
  | VideoMessagePart
  | MediaGroupMessagePart
  | FormMessagePart
  | CommandButtonsMessagePart
  | NoticeMessagePart
  | ErrorMessagePart;

export type Message = {
  message_id: string;
  id?: string | null;
  client_message_id?: string | null;
  session_id: string;
  role: 'user' | 'assistant' | 'agent' | 'system' | 'tool' | 'command';
  speaker_type?: 'user' | 'agent' | 'capability' | 'system' | null;
  speaker_id?: string | null;
  speaker_name?: string | null;
  origin?: string | null;
  agent_id?: string | null;
  command_name?: string | null;
  action_id?: string | null;
  run_id?: string | null;
  content_version: 2;
  parts: MessagePart[];
  parent_message_id?: string | null;
  metadata?: Record<string, unknown>;
  run?: Run;
  run_steps?: RunStep[];
  available_actions: AvailableAction[];
  created_at: string;
  client_status?: 'pending' | 'failed' | 'preparing' | 'streaming';
  client_error?: AppError;
};

export type SystemNotification = {
  id: string;
  session_id: string;
  run_id?: string | null;
  severity: 'info' | 'warning' | 'error' | string;
  code?: string | null;
  message: string;
  created_at: string;
  metadata?: Record<string, unknown>;
};

export type TimelineItem =
  | { kind: 'message'; message: Message }
  | { kind: 'notification'; notification: SystemNotification };

export type SendMessageAttachment = Attachment;

export type AppError = {
  code: string;
  message: string;
  details?: Record<string, unknown>;
};

export type Run = {
  run_id: string;
  session_id: string;
  kind: 'agent' | 'command' | 'action' | 'resume';
  status: string;
  target_id: string;
  action_id?: string | null;
  current_step: string;
  stage?: string;
  progress_message?: string;
  progress_current?: number | null;
  progress_total?: number | null;
  cancel_requested?: boolean;
  started_at?: string | null;
  finished_at?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  error?: string | null;
  metadata?: Record<string, unknown>;
  steps?: RunStep[];
  created_at: string;
  updated_at: string;
};

export type RunStep = {
  step_id: string;
  run_id: string;
  parent_step_id?: string | null;
  label: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | string;
  message?: string;
  order: number;
  started_at?: string | null;
  finished_at?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type RunEvent = {
  event_id: string;
  run_id: string;
  session_id: string;
  type: string;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type RuntimeEvent = {
  type: string;
  session_id: string;
  run_id?: string | null;
  message_id?: string | null;
  payload: Record<string, unknown>;
  created_at: string;
};

export type HealthDetails = {
  status: 'ok' | 'degraded';
  version: string;
  database: { status: string; error?: string };
  schema_version: string;
  registries: { agents: number; capabilities: number; commands: number };
  llm: {
    status: string;
    base_url?: string;
    model?: string;
    timeout?: number | null;
    api_key_set?: boolean;
    error?: string;
  };
};

export type RuntimeResponse = {
  success: boolean;
  data: unknown;
  error?: string | null;
  ok?: boolean;
  message?: string | null;
  silent?: boolean;
  run_id?: string | null;
  run?: Run | null;
  session?: Session;
  updated_form?: {
    source_message_id: string;
    form_id: string;
    block: ActionFormBlock;
  } | null;
  messages: Message[];
};

export type RuntimeMemoryTarget = 'llm' | 'comfyui' | 'embedding' | 'reranker' | 'all';

export type RuntimeMemoryTargetSummary = {
  target: Exclude<RuntimeMemoryTarget, 'all'>;
  available: boolean;
  enabled: boolean;
  reason: string;
  status: 'loaded' | 'not_loaded' | 'busy' | 'unavailable' | 'unknown' | string;
};

export type RuntimeMemorySummary = {
  targets: RuntimeMemoryTargetSummary[];
};

export type RuntimeMemoryResultItem = {
  target: Exclude<RuntimeMemoryTarget, 'all'>;
  status: 'freed' | 'skipped' | 'busy' | 'unavailable' | 'failed' | string;
  message: string;
};

export type RuntimeMemoryFreeResult = {
  results: RuntimeMemoryResultItem[];
};

export type RuntimeResourceCpu = {
  available: boolean;
  percent: number | null;
  reason?: string | null;
  warnings?: string[];
};

export type RuntimeResourceMemory = {
  available: boolean;
  used_bytes: number | null;
  total_bytes: number | null;
  percent: number | null;
  reason?: string | null;
};

export type RuntimeResourceGpu = {
  index: number;
  name: string;
  available: boolean;
  utilization_percent: number | null;
  memory_used_bytes: number | null;
  memory_total_bytes: number | null;
  memory_percent: number | null;
  backend?: string;
  reason?: string | null;
};

export type RuntimeResources = {
  cpu: RuntimeResourceCpu;
  memory: RuntimeResourceMemory;
  gpus: RuntimeResourceGpu[];
  process: {
    backend_memory_bytes: number | null;
    reason?: string | null;
  };
  updated_at: string | null;
  error?: string | null;
};

export type UtilityLlmStatus = {
  available: boolean;
  configured: boolean;
  loaded: boolean;
  backend: 'transformers' | 'llama_cpp' | 'model_profile' | string;
  model_path: string | null;
  model_profile_id?: string | null;
  model_profile_name?: string | null;
  provider_profile_id?: string | null;
  provider_label?: string | null;
  requested_model_id?: string | null;
  device: 'auto' | 'cpu' | 'cuda' | string | null;
  resolved_device?: string | null;
  options?: {
    context_size: number;
    gpu_layers: number;
    threads: number | null;
  };
  backend_status: {
    transformers_available?: boolean;
    torch_available?: boolean;
    llama_cpp_available?: boolean;
    cuda_available?: boolean;
    type?: string;
    profile_enabled?: boolean;
    provider_enabled?: boolean | null;
    provider?: string | null;
    api_key_set?: boolean;
  };
  reason?: string | null;
  warnings?: string[];
};

export type UtilityLlmModelScanItem = {
  model_path: string;
  name: string;
  type: 'transformers' | 'llama_cpp';
  exists: boolean;
  folder?: string;
};

export type UtilityLlmModelScan = {
  models_root: string;
  utility_root: string;
  transformers_models: UtilityLlmModelScanItem[];
  gguf_models: UtilityLlmModelScanItem[];
  backend: {
    transformers_available: boolean;
    torch_available: boolean;
    llama_cpp_available: boolean;
    cuda_available: boolean;
  };
  warnings: string[];
};

export type SemanticRouterStatus = {
  status: 'ready' | 'no_profile_selected' | 'profile_unavailable' | 'embedding_backend_unavailable' | string;
  embedding_model_profile_id?: string | null;
  candidate_summary: {
    intent_examples: number;
    knowledge_bases: number;
    agents: number;
    actions: number;
    commands: number;
    total: number;
  };
  index?: {
    version?: string | null;
    stale?: boolean;
    will_rebuild_lazily?: boolean;
  };
};

export type UtilityLlmTitleTestResult = {
  ok: boolean;
  title?: string;
  backend: string;
  model_profile_id?: string | null;
  model_profile_name?: string | null;
  provider_profile_id?: string | null;
  provider_label?: string | null;
  requested_model_id?: string | null;
  warnings: string[];
  reason?: string;
  error?: { code: string; message: string };
};

export type UtilityLlmJsonTestResult = {
  ok: boolean;
  backend?: string;
  model_profile_id?: string | null;
  model_profile_name?: string | null;
  provider_label?: string | null;
  requested_model_id?: string | null;
  result?: {
    intent: string;
    confidence: number;
    slots: Record<string, string>;
  };
  warnings: string[];
  reason?: string;
  error?: { code: string; message: string };
};

export type DeleteSessionResponse = {
  deleted: boolean;
  session_id: string;
};

export type DeleteMessageResponse = {
  deleted: boolean;
  message_id: string;
};

export type DismissNotificationResponse = {
  ok: boolean;
  notification_id: string;
  dismissed: boolean;
};

export type GeneralSettings = {
  max_image_size_mb: number;
  max_file_size_mb: number;
  max_attachments_per_message: number;
  max_file_context_per_file_kb: number;
  max_total_file_context_per_message_kb: number;
  send_text_file_attachments_to_llm: boolean;
  persist_streaming_message_deltas: boolean;
  auto_generate_session_titles: boolean;
  session_title_backend: 'utility_llm' | 'follow_agent_model_profile' | 'specified_model_profile';
  session_title_model_profile_id: string | null;
  session_title_unload_after_generation: boolean;
  session_title_prompt: string;
  session_title_prompt_default: string;
  session_title_max_input_chars: number;
  group_transcript_system_instruction: string | null;
  group_transcript_system_instruction_default: string;
  group_transcript_system_instruction_effective: string;
  command_result_context_instruction: string | null;
  command_result_context_instruction_default: string;
  command_result_context_instruction_effective: string;
  resource_status_panel_enabled: boolean;
  resource_status_show_cpu: boolean;
  resource_status_show_ram: boolean;
  resource_status_show_gpu: boolean;
  resource_status_show_vram: boolean;
  resource_status_ram_display_mode: 'percent' | 'value';
  resource_status_vram_display_mode: 'percent' | 'value';
  resource_status_show_tokens: boolean;
  appearance_font_ui_family: string;
  appearance_font_message_family: string;
  appearance_font_code_family: string;
  appearance_font_ui_source: FontSource;
  appearance_font_message_source: FontSource;
  appearance_font_code_source: FontSource;
  appearance_font_ui_system_name: string;
  appearance_font_message_system_name: string;
  appearance_font_code_system_name: string;
  appearance_font_ui_custom_id: string | null;
  appearance_font_message_custom_id: string | null;
  appearance_font_code_custom_id: string | null;
  appearance_font_ui_custom_family_id: string | null;
  appearance_font_message_custom_family_id: string | null;
  appearance_font_code_custom_family_id: string | null;
  core_memory_content: string;
  core_memory_enabled_for_prompt_agents: boolean;
  core_memory_enabled_for_script_agents: boolean;
  web_context_enabled: boolean;
  web_context_max_results: number;
  web_context_context_budget_chars: number;
  web_context_prompt: string;
  web_context_prompt_default: string;
  web_context_plan_resolver_prompt: string;
  web_context_plan_resolver_prompt_default: string;
  web_context_candidate_judge_prompt: string;
  web_context_candidate_judge_prompt_default: string;
  web_context_page_excerpt_gate_prompt: string;
  web_context_page_excerpt_gate_prompt_default: string;
  web_context_fetch_pages_enabled: boolean;
  web_context_page_cleaning_enabled: boolean;
  web_context_fetch_max_pages: number;
  web_context_fetch_timeout_seconds: number;
  web_context_fetch_max_bytes: number;
  web_context_page_excerpt_chars: number;
  web_context_total_page_excerpt_chars: number;
  web_context_target_page_excerpts: number;
  web_context_page_excerpt_gate_enabled: boolean;
  web_context_page_excerpt_gate_backend: 'follow_agent_model_profile' | 'specific_model_profile' | 'utility_llm';
  web_context_page_excerpt_gate_model_profile_id: string | null;
  web_context_page_excerpt_gate_min_quality: 'low' | 'medium' | 'high';
  web_context_candidate_judge_enabled: boolean;
  web_context_candidate_judge_max_candidates: number;
  web_context_candidate_judge_min_relevance: 'low' | 'medium' | 'high';
  intent_routing_enabled: boolean;
  intent_routing_default_for_prompt_agents: boolean;
  intent_routing_mode: 'shadow' | 'auto';
  intent_routing_semantic_intent_min_score: number;
  intent_routing_semantic_intent_min_margin: number;
  intent_routing_semantic_kb_min_score: number;
  intent_routing_semantic_agent_min_score: number;
  intent_routing_semantic_command_min_score: number;
  intent_routing_auto_route_safe_intents: boolean;
  intent_routing_confirm_uncertain: boolean;
  intent_routing_embedding_model_profile_id: string | null;
  intent_routing_utility_llm_backend: 'transformers' | 'llama_cpp' | 'model_profile';
  intent_routing_utility_llm_model_profile_id: string | null;
  intent_routing_utility_llm_model_path: string;
  intent_routing_utility_llm_context_size: number;
  intent_routing_utility_llm_gpu_layers: number;
  intent_routing_utility_llm_threads: number | null;
  intent_routing_device: 'auto' | 'cpu' | 'cuda';
  intent_routing_chat_examples: string;
  intent_routing_image_generation_examples: string;
  intent_routing_knowledge_query_examples: string;
  intent_routing_web_query_examples: string;
  intent_routing_agent_route_examples: string;
  intent_routing_command_like_examples: string;
};

export type FontSource = 'system' | 'custom_file' | 'custom_family';

export type FontAsset = {
  id: string;
  filename: string;
  display_name: string;
  extension: '.woff2' | '.woff' | '.ttf' | '.otf' | string;
  size_bytes: number;
  mtime: number;
  css_family: string;
  url: string;
};

export type FontFamilyFace = {
  file: string;
  weight: number | string;
  style: 'normal' | 'italic' | string;
  url: string;
  registered_weight: string;
};

export type FontFamilyAsset = {
  id: string;
  display_name: string;
  css_family: string;
  faces: FontFamilyFace[];
};

export type FontAssetsResponse = {
  fonts: FontAsset[];
  files: FontAsset[];
  families: FontFamilyAsset[];
};

export type IntentRouteTestResponse = {
  ok: boolean;
  decision: Record<string, unknown>;
};

export type StorageStats = {
  database: {
    status: string;
    path: string;
    size_bytes: number;
    schema_version: string;
  };
  attachments: {
    directory: string;
    count: number;
    total_size_bytes: number;
    orphan_count: number;
    orphan_size_bytes: number;
    last_scan_time?: string;
  };
  warnings?: string[];
};

export type Diagnostics = {
  backend: {
    status: string;
    version?: string;
    python_version?: string;
    uptime_seconds?: number;
  };
  database: {
    status: string;
    schema_version?: string;
    path?: string;
    size_bytes?: number;
  };
  attachments: {
    status: string;
    directory?: string;
    count?: number;
    total_size_bytes?: number;
    writable?: boolean;
  };
  event_bus: {
    status: string;
    subscriber_count?: number;
    active_websocket_connections?: number;
  };
  runs: {
    active_count: number;
    active_task_count?: number;
    recent_failed_count: number;
    recent_failures: DiagnosticsRunFailure[];
  };
  llm: {
    status?: string;
    profiles_total: number;
    profiles_enabled: number;
    global_fallback_enabled?: boolean;
    default_resolved?: {
      profile?: string | null;
      model_id?: string | null;
      base_url?: string;
      api_key_set: boolean;
    } | null;
    last_error?: string | null;
  };
  capabilities: {
    file: {
      enabled: boolean;
      status: string;
      allowed_directories_count?: number;
      max_read_file_size_bytes?: number;
      max_local_text_read_size_mb?: number;
      max_local_image_read_size_mb?: number;
      max_local_audio_read_size_mb?: number;
      max_local_video_read_size_mb?: number;
      read_file_enabled?: boolean;
    };
    http: {
      enabled: boolean;
      status: string;
      timeout_seconds?: number;
      max_response_size_bytes?: number;
      max_text_response_size_mb?: number;
      max_image_response_size_mb?: number;
      fetch_url_enabled?: boolean;
      allow_redirects?: boolean;
    };
  };
  warnings: string[];
};

export type DiagnosticsRunFailure = {
  run_id: string;
  session_id: string;
  agent_id?: string | null;
  command_name?: string | null;
  error_code: string;
  message: string;
  created_at: string;
};

export type OrphanAttachment = {
  id: string;
  path: string;
  size_bytes: number;
};

export type OrphanScanResult = {
  orphan_count: number;
  orphan_size_bytes: number;
  orphans: OrphanAttachment[];
};

export type CleanupOrphansResult = {
  deleted_count: number;
  deleted_size_bytes: number;
  errors: { path?: string; error?: string }[];
};
