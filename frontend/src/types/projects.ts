import type { ContextPolicy } from './chat';

type ProjectSettings = {
  name: string;
  context_policy: ContextPolicy;
  model_profile_id: string | null;
  temperature: number | null;
};

export type WorkspaceInput = ProjectSettings & {
  kind: 'workspace';
  agent_persona_id: string;
  cogita_persona_id: string;
  harness_enabled: boolean;
  tools_allowed: string[];
  system_prompt: string;
  knowledge_base_ids: string[];
};

export type TimelineInput = ProjectSettings & {
  kind: 'timeline';
  character_persona_id: string;
  user_persona_id: string;
  worldbook_ids: string[];
};

export type ProjectInput = WorkspaceInput | TimelineInput;
export type ProjectKind = ProjectInput['kind'];
type ProjectIdentity = { id: string; created_at: string; updated_at: string };
export type WorkspaceProject = WorkspaceInput & ProjectIdentity;
export type TimelineProject = TimelineInput & ProjectIdentity;
export type Project = WorkspaceProject | TimelineProject;
export type ProjectPatch = Partial<Omit<WorkspaceInput, 'kind'>> | Partial<Omit<TimelineInput, 'kind'>>;
