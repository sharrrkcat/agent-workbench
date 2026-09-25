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

export type SessionGenerationParameters = { temperature?: number | null };
export type PersonaCollection = 'user' | 'agent' | 'roleplay_user' | 'character';

export type PersonaInput = {
  name: string;
  avatar_attachment_id: string | null;
  system_prompt: string;
};

export type PersonaCreate = PersonaInput & { collection: Exclude<PersonaCollection, 'user'> };
export type Persona = PersonaInput & {
  id: string; collection: PersonaCollection; is_protected: boolean; created_at: string; updated_at: string;
};
export type PersonaIdentity = Pick<Persona, 'id' | 'name' | 'avatar_attachment_id'>;

export type OrdinarySessionPatch = Partial<{
  title: string;
  persona_id: string;
  model_profile_id: string | null;
  context_policy: ContextPolicy;
  generation: SessionGenerationParameters;
  harness_enabled: boolean;
  tools_allowed: string[];
}>;

export type WorkspaceOverrides = {
  persona_id?: string | null;
  model_profile_id?: string | null;
  context_policy?: ContextPolicy | null;
  temperature?: number | null;
  harness_enabled?: boolean | null;
  tools_allowed?: string[] | null;
};
export type WorkspaceSessionPatch = { title?: string; overrides?: WorkspaceOverrides };
export type SessionPatch = OrdinarySessionPatch | WorkspaceSessionPatch;

export type EffectiveChatConfig = {
  session_kind: 'ordinary' | 'workspace';
  project_id: string | null;
  sources: {
    persona: 'session' | 'project';
    context: 'session' | 'project';
    temperature: 'session' | 'project' | 'model';
    harness: 'session' | 'project';
    tools: 'session' | 'project';
  };
  persona_id: string;
  persona_name: string;
  avatar_attachment_id: string | null;
  model_profile_id: string | null;
  model_source: 'session' | 'project' | 'global';
  user_persona_id: string;
  context_policy: ContextPolicy;
  generation: GenerationParameters;
  harness_enabled: boolean;
  tools_allowed: string[];
  knowledge_base_ids: string[];
};

type SessionBase = {
  session_id: string;
  title: string;
  waiting_run_id: string | null;
  user_persona: PersonaIdentity;
  effective: EffectiveChatConfig;
  title_generation_state?: string;
  title_generation_metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type OrdinarySession = SessionBase & {
  kind: 'ordinary';
  project_id: null;
  model_profile_id: string | null;
  persona_id: string;
  context_policy: ContextPolicy;
  generation: SessionGenerationParameters;
  harness_enabled: boolean;
  tools_allowed: string[];
};

export type WorkspaceSession = SessionBase & {
  kind: 'workspace';
  project_id: string;
  overrides: WorkspaceOverrides;
};

export type Session = OrdinarySession | WorkspaceSession;
