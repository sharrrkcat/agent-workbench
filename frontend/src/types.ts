export type AgentAction = {
  id: string;
  label?: string | null;
  description: string;
  instruction?: string | null;
  callable: boolean;
};

export type Agent = {
  id: string;
  name: string;
  type: 'prompt' | 'script';
  description: string;
  avatar: string;
  actions: AgentAction[];
  enabled: boolean;
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
  avatar?: string;
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

export type LlmResolvedConfig = {
  base_url: string;
  model: string;
  timeout?: number | null;
  api_key_set: boolean;
  sources?: Record<string, string>;
};

export type Session = {
  session_id: string;
  title: string;
  default_agent_id: string;
  waiting_run_id?: string | null;
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
  available_actions: AvailableAction[];
  created_at: string;
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
  messages: Message[];
};
