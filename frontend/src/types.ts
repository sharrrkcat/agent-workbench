/** Shared transport types for the compact Phase 1 client. */

export type ContextMode = 'single_assistant' | 'group_transcript';

export type Session = {
  session_id: string;
  title: string;
  context_mode: ContextMode;
  waiting_run_id: string | null;
  llm_profile_id: string | null;
  last_announced_llm_profile_id?: string | null;
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
export type MediaGroupPart = { id: string; type: 'media_group'; layout?: 'gallery'; items: Array<Pick<ImagePart, 'type' | 'url' | 'attachment_id' | 'alt' | 'title' | 'caption'>> };
export type MessagePart = TextPart | JsonPart | FilePart | ImagePart | AudioPart | VideoPart | NoticePart | ErrorPart | MediaGroupPart;

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
export type RunKind = 'chat' | 'resume';
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
  target: string;
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
  utility_model_profile_id: string | null;
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
  inference_service_enabled: boolean;
  inference_service_require_api_key: boolean;
  inference_service_max_request_mb: number;
  inference_service_api_key?: string | null;
  inference_service_api_key_set?: boolean;
  pet: PetSettings;
  [key: string]: unknown;
};

export type LlmDefaults = { default_model_profile_id: string | null };
export type LlmProfile = {
  id: string;
  alias: string;
  name: string;
  provider_profile_id?: string | null;
  provider: string;
  base_url: string;
  api_key?: string;
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
  external_inference_enabled: boolean;
  notes?: string | null;
  created_at: string;
  updated_at: string;
};
export type LlmProfileInput = Partial<Omit<LlmProfile, 'id' | 'created_at' | 'updated_at' | 'api_key_set'>> & { alias: string; name: string; model_id: string };
export type LlmProviderProfile = { id: string; name: string; provider: string; base_url: string; api_key?: string; api_key_set?: boolean; timeout_seconds?: number | null; enabled: boolean; metadata?: Record<string, unknown>; created_at: string; updated_at: string };
export type LlmProviderProfileInput = Partial<Omit<LlmProviderProfile, 'id' | 'created_at' | 'updated_at' | 'api_key_set'>> & { name: string };

export type KnowledgeSettings = {
  id: number;
  models_root: string;
  local_model_device: 'auto' | 'cpu' | 'cuda';
  embedding_batch_size: number;
  embedding_timeout_seconds: number;
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
export type EmbeddingModelProfile = { id: string; name: string; alias: string; model_path: string; provider_profile_id?: string | null; provider_model_id: string; dimension?: number | null; normalize: boolean; document_instruction: string; query_instruction: string; enabled: boolean; external_inference_enabled: boolean; notes: string; created_at: string; updated_at: string };
export type KnowledgeBase = { id: string; name: string; description: string; aliases_text: string; embedding_model_profile_id: string; enabled: boolean; index_status: string; index_error?: string | null; vector_candidate_k_override?: number | null; keyword_candidate_k_override?: number | null; final_top_k_override?: number | null; max_context_chars_override?: number | null; created_at: string; updated_at: string };
export type KnowledgeSource = { id: string; knowledge_base_id: string; source_type: 'pasted_text' | 'attachment_text' | 'file'; uri: string; title: string; relative_path?: string; status: string; error?: string | null; chunks: number; indexed_at?: string | null; created_at: string; updated_at: string; [key: string]: unknown };
export type SessionKnowledgeBinding = { id?: number | null; session_id: string; knowledge_base_id: string; enabled: boolean; sort_order: number; knowledge_base?: KnowledgeBase | null };
export type KnowledgeSearchResponse = { query: string; results: Array<Record<string, unknown>>; metadata?: Record<string, unknown>; debug?: Record<string, unknown>; context_preview?: string };

export type WorldbookSettings = { worldbook_enabled: boolean; worldbook_max_entries_per_call: number; worldbook_max_context_chars: number; worldbook_regex_case_insensitive: boolean; worldbook_recursion_depth: number; worldbook_case_sensitive: boolean; worldbook_whole_words: boolean };
export type Worldbook = { id: string; name: string; description: string; enabled: boolean; entry_count?: number; active_binding_count?: number; created_at: string; updated_at: string };
export type WorldbookEntry = { id: string; worldbook_id: string; name: string; keywords_text: string; content: string; activation_mode: string; enabled: boolean; sort_order: number; created_at: string; updated_at: string };
export type SessionWorldbooksResponse = { session_id: string; enabled_worldbooks: Array<Record<string, unknown>>; available_worldbooks: Worldbook[]; warnings?: string[] };
export type RuntimeEvent = { type: string; session_id: string; run_id?: string; message_id?: string; payload?: Record<string, unknown>; created_at?: string };
export type SendMessageAttachment = Record<string, unknown>;
