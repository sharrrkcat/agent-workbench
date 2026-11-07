import type { MemoryIsolation } from './memory';

export type ContextPolicy = {
  history_enabled: boolean;
  strategy: 'token_budget' | 'message_window' | 'history_retrieval';
  include_attachments: 'none' | 'explicit';
  compaction: { enabled: boolean; trigger_percent: number; target_percent: number; max_summary_tokens: number | null };
  message_window: { max_messages: number };
  retrieval: { trigger_percent: number; target_percent: number; max_checkpoint_tokens: number | null };
};

export const defaultContextPolicy = (): ContextPolicy => ({ history_enabled: true, strategy: 'token_budget', include_attachments: 'explicit',
  message_window: { max_messages: 100 },
  retrieval: { trigger_percent: 80, target_percent: 55, max_checkpoint_tokens: null },
  compaction: { enabled: true, trigger_percent: 80, target_percent: 55, max_summary_tokens: null } });

export const USER_PERSONA_ID = '00000000-0000-4000-8000-000000000004';
export const COGITA_CHARACTER_ID = '00000000-0000-4000-8000-000000000003';

export type GenerationParameters = {
  temperature?: number | null; top_p?: number | null; max_tokens?: number | null;
  presence_penalty?: number | null; frequency_penalty?: number | null; seed?: number | null; stop?: string | string[] | null;
};
export type SessionGenerationParameters = { temperature?: number | null };

export type PersonaInput = { name: string; avatar_attachment_id: string | null; background: string };
export type Persona = PersonaInput & { id: string; is_protected: boolean; created_at: string; updated_at: string };
export type PersonaIdentity = Pick<Persona, 'id' | 'name' | 'avatar_attachment_id'>;

export type ChatDefaults = {
  persona_id: string; model_profile_id: string | null; temperature: number | null;
  reasoning: boolean; context_policy: ContextPolicy; harness_enabled: boolean; tools_allowed: string[];
  knowledge_base_ids: string[]; worldbook_ids: string[];
  memory_enabled: boolean;
};
export type SessionOverrides = { [K in keyof ChatDefaults]?: ChatDefaults[K] | null };
export type SessionPatch = { title?: string; overrides?: SessionOverrides; memory_isolation?: MemoryIsolation };

export type EffectiveChatConfig = {
  qq_reply_message_limit: number | null;
  context_limits: { window_tokens: number | null; output_tokens: number | null };
  session_kind: 'normal' | 'qqbot';
  character_id: string; character_name: string; character_avatar_attachment_id: string | null;
  persona_id: string | null; persona_name: string | null;
  sources: {
    persona: 'session' | 'character' | 'binding'; context: 'session' | 'character';
    memory: 'session' | 'character';
    temperature: 'session' | 'character' | 'model'; reasoning: 'session' | 'character';
    harness: 'session' | 'character'; tools: 'session' | 'character';
    knowledge: 'session' | 'character'; worldbook: 'session' | 'character';
  };
  model_profile_id: string | null; model_source: 'session' | 'character';
  context_policy: ContextPolicy; generation: GenerationParameters;
  reasoning: boolean; harness_enabled: boolean; tools_allowed: string[];
  knowledge_base_ids: string[]; worldbook_ids: string[];
  memory_enabled: boolean;
};

type SessionBase = {
  session_id: string; character_id: string; title: string; waiting_run_id: string | null;
  effective: EffectiveChatConfig; title_generation_state?: string; title_generation_metadata?: Record<string, unknown>;
  created_at: string; updated_at: string;
};
export type NormalSession = SessionBase & { kind: 'normal'; overrides: SessionOverrides; persona: PersonaIdentity;
  bound_persona_id: string | null; memory_isolation: MemoryIsolation; memory_version: number };
export type QQSession = SessionBase & { kind: 'qqbot'; persona: null; target_kind: 'group' | 'friend'; target_id: string };
export type Session = NormalSession | QQSession;
export type ChatDraft = { kind: 'normal'; character_id: string; title: string; overrides: SessionOverrides; memory_isolation?: MemoryIsolation };
