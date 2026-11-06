import type { ChatDefaults, ContextPolicy } from './chat';

type CharacterSettings = {
  name: string; avatar_attachment_id: string | null; system_prompt: string;
  model_profile_id: string | null; temperature: number | null;
};
export type NormalCharacterInput = CharacterSettings & ChatDefaults & { kind: 'normal' };
export type QQBotInput = CharacterSettings & {
  context_policy: ContextPolicy;
  kind: 'qqbot'; bot_account: string; admin_qq: string | null; websocket_url: string; access_token?: string;
  connection_enabled: boolean;
  reasoning: boolean; group_reply_mode: 'keyword'; keywords: string[]; batch_message_limit: number;
  reply_message_limit: number; image_input_enabled: boolean;
  icebreaker_enabled: boolean; icebreaker_cold_seconds: number;
  icebreaker_wait_seconds: number; icebreaker_cooldown_seconds: number;
  image_description_model_profile_id: string | null;
  image_generation_model_profile_id: string | null;
  image_generation_options: {
    size: string | null;
    quality: 'auto' | 'low' | 'medium' | 'high' | 'standard' | 'hd' | null;
    style: 'natural' | 'vivid' | null;
  };
};
type CharacterIdentity = { id: string; is_protected: boolean; created_at: string; updated_at: string };
export type NormalCharacter = NormalCharacterInput & CharacterIdentity;
export type QQBotCharacter = Omit<QQBotInput, 'access_token'> & CharacterIdentity & { has_access_token: boolean };
export type CharacterInput = NormalCharacterInput | QQBotInput;
export type CharacterKind = CharacterInput['kind'];
export type Character = NormalCharacter | QQBotCharacter;
export type CharacterPatch = Partial<Omit<NormalCharacterInput, 'kind'>> | Partial<Omit<QQBotInput, 'kind'>>;
