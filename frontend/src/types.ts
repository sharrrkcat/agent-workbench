/** Shared transport types for the compact Phase 1 client. */

export type ContextMode = 'single_assistant' | 'group_transcript';
export type BindingMode = 'inherit' | 'override';
export type ContextPolicy = {
  mode: 'none' | 'current_message' | 'recent_messages' | 'session' | 'selected_message';
  max_messages: number | null; max_chars: number | null;
  include_system_prompt: boolean; include_attachments: 'none' | 'explicit';
};
export type GenerationParameters = {
  temperature?: number | null; top_p?: number | null; max_tokens?: number | null;
  presence_penalty?: number | null; frequency_penalty?: number | null; seed?: number | null;
  stop?: string | string[] | null;
};
export type PersonaInput = {
  name: string; avatar_attachment_id: string | null; system_prompt: string;
  model_profile_id: string | null; context_policy: ContextPolicy; generation: GenerationParameters;
  harness_enabled: boolean; tools_allowed: string[];
};
export type Persona = PersonaInput & { id: string; created_at: string; updated_at: string };
export type SessionPersona = { persona_id: string; enabled: boolean; name: string; avatar_attachment_id: string | null };
export type SessionPatch = Partial<{
  title: string; context_mode: ContextMode; current_persona_id: string;
  personas: Array<Pick<SessionPersona, 'persona_id' | 'enabled'>>;
  model_profile_id: string | null; context_policy: ContextPolicy | null;
  generation: GenerationParameters | null; harness_enabled: boolean | null; tools_allowed: string[] | null;
  knowledge_binding_mode: BindingMode; worldbook_binding_mode: BindingMode;
}>;
export type EffectiveChatConfig = {
  persona_id: string; persona_name: string; avatar_attachment_id: string | null;
  model_profile_id: string | null; model_source: 'session' | 'persona' | 'global';
  context_mode: ContextMode; context_policy: ContextPolicy; generation: GenerationParameters;
  harness_enabled: boolean; tools_allowed: string[]; knowledge_base_ids: string[]; worldbook_ids: string[];
};

export type Session = {
  session_id: string;
  title: string;
  context_mode: ContextMode;
  waiting_run_id: string | null;
  model_profile_id: string | null;
  current_persona_id: string;
  personas: SessionPersona[];
  context_policy: ContextPolicy | null;
  generation: GenerationParameters | null;
  harness_enabled: boolean | null;
  tools_allowed: string[] | null;
  knowledge_binding_mode: BindingMode;
  worldbook_binding_mode: BindingMode;
  effective: EffectiveChatConfig;
  title_generation_state?: string;
  title_generation_metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type MessageRole = 'user' | 'assistant' | 'system' | 'tool';

export type TextPart = { id: string; type: 'text'; format?: 'plain' | 'markdown'; text: string };
export type JsonPart = { id: string; type: 'json'; data: unknown };
export type FilePart = {
  id: string;
  type: 'file';
  mode?: 'inline_text' | 'attachment_ref';
  content?: string;
  attachment_id?: string;
  filename?: string;
  language?: string;
  mime_type?: string;
  size?: number;
  truncated?: boolean;
  path?: string;
};
export type ImagePart = { id: string; type: 'image'; url?: string; attachment_id?: string; alt?: string; title?: string; caption?: string };
export type AudioPart = { id: string; type: 'audio'; source?: 'attachment' | 'url'; attachment_id?: string; url: string; mime_type: string; filename?: string; title?: string; duration_ms?: number };
export type VideoPart = { id: string; type: 'video'; source?: 'attachment' | 'url'; attachment_id?: string; url: string; mime_type: string; filename?: string; title?: string; poster_url?: string };
export type NoticePart = { id: string; type: 'notice'; level?: 'info' | 'warning' | 'success'; text: string };
export type ErrorPart = { id: string; type: 'error'; code?: string; message: string };
export type ToolCallPart = { id: string; type: 'tool_call'; tool_call_id: string; tool_name: string; arguments: Record<string, unknown> };
export type ToolResultPart = { id: string; type: 'tool_result'; tool_call_id: string; tool_name: string; status: 'success' | 'error' | 'rejected' | 'cancelled'; data?: unknown; error_code?: string; error_message?: string; truncated?: boolean };
export type MediaGroupPart = { id: string; type: 'media_group'; layout?: 'gallery'; items: Array<Pick<ImagePart, 'type' | 'url' | 'attachment_id' | 'alt' | 'title' | 'caption'>> };
export type MessagePart = TextPart | JsonPart | FilePart | ImagePart | AudioPart | VideoPart | NoticePart | ErrorPart | MediaGroupPart | ToolCallPart | ToolResultPart;

export type Message = {
  message_id: string;
  session_id: string;
  role: MessageRole;
  speaker_type?: string | null;
  speaker_id?: string | null;
  speaker_name?: string | null;
  origin?: string | null;
  content_version?: number;
  parts: MessagePart[];
  run_id?: string | null;
  parent_message_id?: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
  run?: Run;
};

export type RunStatus = 'PENDING' | 'RUNNING' | 'CANCELLING' | 'WAITING_FOR_USER' | 'DONE' | 'FAILED' | 'CANCELLED' | 'INTERRUPTED';
export type RunKind = 'chat' | 'tool';
export type RunStepKind = 'context' | 'model' | 'save' | 'approval' | 'tool';
export type RunStepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
export type RunStep = {
  step_id: string;
  run_id: string;
  kind: RunStepKind;
  parent_step_id?: string | null;
  label: string;
  status: RunStepStatus;
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
export type Run = {
  run_id: string;
  session_id: string;
  kind: RunKind;
  status: RunStatus;
  persona_id: string;
  current_step?: string;
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
  created_at: string;
  updated_at: string;
  steps?: RunStep[];
};
export type RunEvent = { event_id: string; run_id: string; session_id: string; type: string; message?: string; payload?: Record<string, unknown>; created_at: string };
export type RuntimeResponse = { success: boolean; data?: unknown; error?: string | null; error_code?: string | null; run?: Run | null; session?: Session; messages?: Message[] };

export type Attachment = { id: string; name: string; filename?: string; mime_type?: string; size_bytes?: number; uri?: string; url?: string; context_text?: string; text?: string; type?: string; [key: string]: unknown };

export type PetPosition = { mode: 'default' | 'custom'; x: number | null; y: number | null };
export type PetBubbleTexts = { idle: string; waiting: string; done: string; failed: string; cancelled: string; interrupted: string; wake: string; tuck: string; status: string; select: string; reload: string; no_pet: string; import_success: string; import_failed: string; delete_success: string; delete_failed: string };
export type PetSettings = { pet_enabled: boolean; default_pet_id: string; pet_scale: number; show_status_bubble: boolean; bubble_offset_x: number; bubble_offset_y: number; jump_on_hover: boolean; running_prefix: string; position: PetPosition; bubble_texts: PetBubbleTexts };
export type PetItem = { id: string; display_name: string; description?: string; valid: boolean; status?: string; errors?: string[]; spritesheet_url?: string | null; can_delete?: boolean; is_builtin?: boolean };
export type PetSettingsResponse = { settings: PetSettings };
export type PetListResponse = { pets: PetItem[] };

export type GeneralSettings = {
  max_image_size_mb: number;
  max_file_size_mb: number;
  max_attachments_per_message: number;
  max_file_context_per_file_kb: number;
  max_total_file_context_per_message_kb: number;
  send_text_file_attachments_to_llm: boolean;
  persist_streaming_message_deltas: boolean;
  auto_generate_session_titles: boolean;
  session_title_prompt: string;
  session_title_max_input_chars: number;
  group_transcript_system_instruction: string | null;
  resource_status_panel_enabled: boolean;
  resource_status_show_cpu: boolean;
  resource_status_show_ram: boolean;
  resource_status_show_gpu: boolean;
  resource_status_show_vram: boolean;
  resource_status_ram_display_mode: 'percent' | 'value';
  resource_status_vram_display_mode: 'percent' | 'value';
  resource_status_show_tokens: boolean;
  core_memory_content: string;
  core_memory_enabled: boolean;
  pet: PetSettings;
  [key: string]: unknown;
};

export type ModelKind = 'llm' | 'embedding' | 'reranker' | 'image_embedding' | 'vision';
export type ModelCapabilities = { streaming: boolean; tools: boolean; vision: boolean; json_object: boolean; json_schema: boolean };
export type ModelInput = {
  alias: string; name: string; kind: ModelKind; provider_profile_id: string | null;
  model_ref: string; enabled: boolean; external_enabled: boolean;
  capabilities: ModelCapabilities; parameters: Record<string, unknown>;
  lifecycle: { unload: 'manual' | 'after_request' | 'idle'; idle_seconds: number };
  runtime_id: 'llama-server' | 'python-worker' | null;
  runtime_variant: string | null;
  runtime_options: Record<string, string | number>;
};
export type ModelProfile = ModelInput & { id: string; created_at: string; updated_at: string };
export type ProviderInput = {
  name: string; protocol: 'openai_compatible'; base_url: string; api_key?: string;
  timeout_seconds: number; concurrency: number; queue_size: number; queue_timeout_seconds: number; enabled: boolean;
};
export type ProviderProfile = Omit<ProviderInput, 'api_key'> & { id: string; has_api_key: boolean; created_at: string; updated_at: string };
export type ModelSettings = { default_model_profile_id: string | null; utility_model_profile_id: string | null;
  external_enabled: boolean; has_external_api_key: boolean; max_request_mb: number };
export type ModelStatus = { state: 'unknown' | 'ready' | 'unavailable' | 'failed' | 'unloaded';
  residency: 'unknown' | 'loaded' | 'unloaded'; unload_supported: boolean; active: number; queued: number; error_code: string | null;
  runtime?: { runtime_id: string; variant: string; version: string; install_state: RuntimeInstallState; process_state: 'stopped' | 'starting' | 'ready' | 'failed'; job_id: string | null } | null };
export type RuntimeInstallState = 'not_installed' | 'installing' | 'installed' | 'broken' | 'unsupported' | 'interrupted';
export type RuntimeCatalogEntry = { runtime_id: 'llama-server' | 'python-worker'; variant: string; version: string; platform: string; architecture: string; supported: boolean; reason: string | null; kinds: ModelKind[]; options_schema: Record<string, unknown> };
export type RuntimeInstallation = { id: string; runtime_id: string; variant: string; version: string; state: RuntimeInstallState; job_id: string | null; error_code: string | null; updated_at: string };
export type RuntimeJob = { id: string; runtime_id: string; variant: string; version: string; operation: 'install' | 'uninstall'; state: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted'; stage: string; progress_current: number; progress_total: number | null; error_code: string | null; cancel_requested: boolean; revision: number; created_at: string; updated_at: string; finished_at: string | null };
export type RuntimeDownloadSettings = { http_proxy: string | null; pypi_index_url: string | null; pytorch_index_url: string | null; github_release_proxy_url: string | null };
export type ModelInventoryItem = { kind: ModelKind; name: string; model_ref: string; state: string; error_code: string };

export type KnowledgeSettings = {
  id: number;
  reranker_enabled: boolean;
  reranker_model_profile_id: string | null;
  reranker_candidate_limit: number;
  hybrid_search_enabled: boolean;
  default_vector_candidate_k: number;
  default_keyword_candidate_k: number;
  default_final_top_k: number;
  default_max_context_chars: number;
  default_min_score: number | null;
  min_score_threshold: number | null;
  retrieval_max_chunks_per_source: number | null;
  retrieval_max_chunks_per_knowledge_base: number | null;
  rrf_k: number;
  default_chunk_size: number;
  default_chunk_overlap: number;
  max_source_size_bytes: number;
  max_chunks_per_source: number;
  max_total_index_chars_per_source: number;
  knowledge_context_instruction: string;
  knowledge_context_snippet_template: string;
};
export type KnowledgeBase = { id: string; name: string; description: string; aliases_text: string; embedding_model_profile_id: string; enabled: boolean; index_status: string; index_error?: string | null; vector_candidate_k_override?: number | null; keyword_candidate_k_override?: number | null; final_top_k_override?: number | null; max_context_chars_override?: number | null; created_at: string; updated_at: string };
export type KnowledgeSource = { id: string; knowledge_base_id: string; source_type: 'pasted_text' | 'attachment_text' | 'file'; uri: string; title: string; relative_path?: string; status: string; error?: string | null; chunks: number; indexed_at?: string | null; created_at: string; updated_at: string; [key: string]: unknown };
export type SessionKnowledgeBindings = { session_id: string; mode: BindingMode; knowledge_base_ids: string[]; effective_knowledge_base_ids: string[] };
export type KnowledgeSearchResponse = { query: string; results: Array<Record<string, unknown>>; metadata?: Record<string, unknown>; debug?: Record<string, unknown>; context_preview?: string };

export type WorldbookSettings = { worldbook_enabled: boolean; worldbook_max_entries_per_call: number; worldbook_max_context_chars: number; worldbook_regex_case_insensitive: boolean; worldbook_recursion_depth: number; worldbook_case_sensitive: boolean; worldbook_whole_words: boolean };
export type Worldbook = { id: string; name: string; description: string; enabled: boolean; entry_count?: number; active_binding_count?: number; created_at: string; updated_at: string };
export type WorldbookEntry = { id: string; worldbook_id: string; name: string; keywords_text: string; content: string; activation_mode: string; enabled: boolean; sort_order: number; created_at: string; updated_at: string };
export type SessionWorldbooksResponse = { session_id: string; mode: BindingMode; worldbook_ids: string[]; effective_worldbook_ids: string[] };
export type RuntimeEvent = { type: string; session_id: string; run_id?: string; message_id?: string; payload?: Record<string, unknown>; created_at?: string };
export type SendMessageAttachment = Record<string, unknown>;
export type HarnessTool = { name: string; description: string; parameters: Record<string, unknown>; risk: 'safe' | 'file' | 'network'; requires_approval: boolean; direct_callable: boolean };
export type HarnessSettings = { searxng_base_url: string | null };
export type ToolRunResponse = { run: Run; messages: Message[]; session: Session };
