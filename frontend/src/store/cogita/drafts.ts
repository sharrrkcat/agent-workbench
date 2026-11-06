import type { ChatDraft, ChatDefaults, Persona } from '../../types/chat';
import type { NormalCharacter } from '../../types/characters';

export function resolveDraft(draft: ChatDraft, character: NormalCharacter): ChatDefaults {
  const overrides = Object.fromEntries(Object.entries(draft.overrides).filter(([, value]) => value != null));
  return { ...character, ...overrides };
}

export function draftConfiguration(draft: ChatDraft, personas: Persona[], character: NormalCharacter) {
  const effective = resolveDraft(draft, character);
  return { ...effective, character_name: character.name,
    persona_name: personas.find((p) => p.id === effective.persona_id)?.name ?? '' };
}
