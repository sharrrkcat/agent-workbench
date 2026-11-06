import { useCogitaStore } from '../store/useCogitaStore';
import { usePersonasStore } from '../store/usePersonasStore';
import { useCharactersStore } from '../store/useCharactersStore';
import { draftConfiguration } from '../store/cogita/drafts';

export function useChatConfiguration() {
  const session = useCogitaStore((s) => s.currentSession);
  const draft = useCogitaStore((s) => s.chatDraft);
  const personas = usePersonasStore((s) => s.personas);
  const character = useCharactersStore((s) => s.characters.find((p) => p.id === draft?.character_id));
  return session?.effective ?? (draft && character?.kind === 'normal' ? draftConfiguration(draft, personas, character) : null);
}
