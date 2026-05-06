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
  mode: 'none' | 'current_message' | 'recent_messages' | 'session' | 'selected_message';
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
  entry?: string | null;
  actions: AgentAction[];
  model?: Record<string, unknown> | null;
  llm?: AgentLlmConfig | null;
  context_policy?: ContextPolicy;
  model_lifecycle?: ModelLifecyclePolicy;
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
  user_config: Record<string, unknown>;
  resolved_config: Record<string, unknown>;
  config_schema: ConfigFieldSchema[];
  manifest_summary: ManifestSummary;
  created_at: string;
  updated_at: string;
};

export type CapabilityConfig = {
  capability_id: string;
  enabled: boolean;
  user_config: Record<string, unknown>;
  resolved_config: Record<string, unknown>;
  config_schema: ConfigFieldSchema[];
  manifest_summary: ManifestSummary & { commands?: Command[] };
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

export type LlmProfileInput = Partial<
  Pick<
    LlmProfile,
    | 'alias'
    | 'name'
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

export type LlmResolvedConfig = {
  source?: string | null;
  profile_id?: string | null;
  profile_alias?: string | null;
  profile_key?: string | null;
  profile_name?: string | null;
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
  data_url: string;
  width?: number;
  height?: number;
};

export type ChatContentBlock =
  | { type: 'text'; text: string }
  | { type: 'markdown'; text: string }
  | ({ type: 'image' } & ImagePayload);

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

export type SendMessageAttachment = ImageAttachment;

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
