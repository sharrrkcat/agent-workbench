import { useTranslation } from 'react-i18next';
import { usePersonasStore } from '../store/usePersonasStore';

export function usePersonaIdentity() {
  const { t } = useTranslation('personas');
  const { personas, loaded, loading, error } = usePersonasStore();
  return (id: string | null | undefined) => {
    const persona = personas.find((item) => item.id === id);
    return {
      name: persona?.name ?? t(id && loaded && !loading && !error ? 'deletedPersona' : 'assistant'),
      avatar_attachment_id: persona?.avatar_attachment_id ?? null,
    };
  };
}
