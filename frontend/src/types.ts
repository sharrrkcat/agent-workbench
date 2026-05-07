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
  enabled: boolean;
  capability_enabled: boolean;
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
};

export type LlmProfile = {
  id: string;
  alias: string;
  name: string;
  provider_profile_id?: string | null;
  provider: 'openai_compatible' | 'lm_studio' | 'llama_cpp' | 'custom';
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
  name?: string | null;
  type?: 'llm' | 'embedding' | 'unknown' | string;
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
  | 'MODEL_MISMATCH'
  | 'MODEL_STATUS_UNKNOWN'
  | 'UNSUPPORTED'
  | 'UNLOADING'
  | 'UNLOAD_FAILED'
  | 'MODEL_UNLOAD_FAILED';

export type LlmProviderStatusModel = {
  id: string;
  name?: string | null;
  type?: 'llm' | 'embedding' | 'unknown' | string;
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
  error?: { code?: string; message?: string; raw?: string };
};

export type LlmProviderStatusRefreshResponse = {
  providers: LlmProviderStatus[];
};

export type LlmProviderProfile = {
  id: string;
  name: string;
  provider: 'openai_compatible' | 'lm_studio' | 'llama_cpp' | 'custom';
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

export type Session = {
  session_id: string;
  title: string;
  default_agent_id: string;
  waiting_run_id?: string | null;
  llm_profile_id?: string | null;
  last_announced_llm_profile_id?: string | null;
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

export type Attachment = ImageAttachment | FileAttachment;

export type FileContentPayload = {
  filename?: string | null;
  language?: string | null;
  mime_type?: string | null;
  content: string;
  size?: number | null;
  truncated?: boolean;
  path?: string | null;
};

export type ChatContentBlock =
  | { type: 'text'; text: string }
  | { type: 'markdown'; text: string }
  | ({ type: 'image' } & ImagePayload)
  | ({ type: 'file_content' } & FileContentPayload);

export type Message = {
  message_id: string;
  session_id: string;
  role: 'user' | 'assistant' | 'agent' | 'system' | 'tool' | 'command';
  content: unknown;
  agent_id?: string | null;
  command_name?: string | null;
  action_id?: string | null;
  run_id?: string | null;
  output_type: string;
  parent_message_id?: string | null;
  metadata?: Record<string, unknown>;
  available_actions: AvailableAction[];
  created_at: string;
  client_status?: 'pending' | 'failed' | 'streaming';
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
  error?: string | null;
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
  run?: Run | null;
  session?: Session;
  messages: Message[];
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
      read_file_enabled?: boolean;
      read_image_enabled?: boolean;
    };
    http: {
      enabled: boolean;
      status: string;
      timeout_seconds?: number;
      max_response_size_bytes?: number;
      max_text_response_size_mb?: number;
      max_image_response_size_mb?: number;
      http_get_enabled?: boolean;
      fetch_image_enabled?: boolean;
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
