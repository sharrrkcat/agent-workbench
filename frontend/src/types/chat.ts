export type ContextMode = 'single_assistant' | 'group_transcript';

export type ContextPolicy = {
  mode: 'none' | 'current_message' | 'recent_messages' | 'session' | 'selected_message';
  max_messages: number | null;
  max_chars: number | null;
  include_attachments: 'none' | 'explicit';
};

export type GenerationParameters = {
  temperature?: number | null;
  top_p?: number | null;
  max_tokens?: number | null;
  presence_penalty?: number | null;
  frequency_penalty?: number | null;
  seed?: number | null;
  stop?: string | string[] | null;
};

export type PersonaInput = {
  name: string;
  avatar_attachment_id: string | null;
  system_prompt: string;
};

export type Persona = PersonaInput & { id: string; created_at: string; updated_at: string };

export type SessionPersona = {
  persona_id: string;
  enabled: boolean;
  name: string;
  avatar_attachment_id: string | null;
};

export type SessionPatch = Partial<{
  title: string;
  context_mode: ContextMode;
  current_persona_id: string;
  personas: Array<Pick<SessionPersona, 'persona_id' | 'enabled'>>;
  model_profile_id: string | null;
  context_policy: ContextPolicy;
  generation: GenerationParameters;
  harness_enabled: boolean;
  tools_allowed: string[];
}>;

export type EffectiveChatConfig = {
  persona_id: string;
  persona_name: string;
  avatar_attachment_id: string | null;
  model_profile_id: string | null;
  model_source: 'session';
  context_mode: ContextMode;
  context_policy: ContextPolicy;
  generation: GenerationParameters;
  harness_enabled: boolean;
  tools_allowed: string[];
  knowledge_base_ids: string[];
  worldbook_ids: string[];
};

export type Session = {
  session_id: string;
  title: string;
  context_mode: ContextMode;
  waiting_run_id: string | null;
  model_profile_id: string | null;
  current_persona_id: string;
  personas: SessionPersona[];
  context_policy: ContextPolicy;
  generation: GenerationParameters;
  harness_enabled: boolean;
  tools_allowed: string[];
  effective: EffectiveChatConfig;
  title_generation_state?: string;
  title_generation_metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};
