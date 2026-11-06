import { useTranslation } from 'react-i18next';
import { useCharactersStore } from '../store/useCharactersStore';

export function useCharacterIdentity() {
  const { t } = useTranslation('personas');
  const characters = useCharactersStore((state) => state.characters);
  return (id: string | null | undefined) => {
    const character = characters.find((item) => item.id === id);
    return { name: character?.name ?? t('assistant'), avatar_attachment_id: character?.avatar_attachment_id ?? null };
  };
}
