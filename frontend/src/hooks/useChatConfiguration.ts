import { useCogitaStore } from '../store/useCogitaStore';
import { useModelsStore } from '../store/useModelsStore';
import { usePersonasStore } from '../store/usePersonasStore';
import { useProjectsStore } from '../store/useProjectsStore';
import { draftConfiguration } from '../store/cogita/drafts';

export function useChatConfiguration() {
  const session = useCogitaStore((s) => s.currentSession);
  const draft = useCogitaStore((s) => s.chatDraft);
  const personas = usePersonasStore((s) => s.personas);
  const profiles = useModelsStore((s) => s.profiles);
  const preferred = useModelsStore((s) => s.settings?.default_model_profile_id);
  const project = useProjectsStore((s) => s.projects.find((p) => p.id === draft?.project_id));
  return session?.effective ?? (draft ? draftConfiguration(draft, personas, profiles, preferred,
    project?.kind === 'workspace' ? project : undefined) : null);
}
