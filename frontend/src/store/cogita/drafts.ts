import type { ChatDraft, Persona } from '../../types/chat';
import type { ModelProfile } from '../../types/models';
import type { WorkspaceProject } from '../../types/projects';

export function defaultModelId(profiles: ModelProfile[], preferred: string | null | undefined) {
  return profiles.find((p) => p.kind === 'llm' && p.enabled && p.id === preferred)?.id
    ?? profiles.find((p) => p.kind === 'llm' && p.enabled)?.id ?? null;
}

export function draftConfiguration(draft: ChatDraft, personas: Persona[], profiles: ModelProfile[],
  preferred: string | null | undefined, project?: WorkspaceProject) {
  const personaId = draft.kind === 'ordinary' ? draft.persona_id : draft.overrides.persona_id ?? project?.agent_persona_id;
  return {
    persona_name: personas.find((p) => p.id === personaId)?.name ?? '',
    model_profile_id: draft.kind === 'ordinary' ? draft.model_profile_id
      : draft.overrides.model_profile_id ?? project?.model_profile_id ?? defaultModelId(profiles, preferred),
    context_policy: draft.kind === 'ordinary' ? draft.context_policy : draft.overrides.context_policy ?? project?.context_policy,
  };
}
