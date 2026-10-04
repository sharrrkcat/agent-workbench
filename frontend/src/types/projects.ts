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

export type QQBotInput = ProjectSettings & {
  kind: 'qqbot'; bot_account: string; websocket_url: string; access_token?: string;
  connection_enabled: boolean; agent_persona_id: string | null; system_prompt: string;
  reasoning: boolean; group_reply_mode: 'keyword'; keywords: string[]; batch_message_limit: number;
};
export type QQBotProject = Omit<QQBotInput, 'access_token'> & ProjectIdentity & { has_access_token: boolean };
export type ProjectInput = WorkspaceInput | TimelineInput | QQBotInput;
export type ProjectKind = ProjectInput['kind'];
type ProjectIdentity = { id: string; created_at: string; updated_at: string };
export type WorkspaceProject = WorkspaceInput & ProjectIdentity;
export type TimelineProject = TimelineInput & ProjectIdentity;
export type Project = WorkspaceProject | TimelineProject | QQBotProject;
export type ProjectPatch = Partial<Omit<WorkspaceInput, 'kind'>> | Partial<Omit<TimelineInput, 'kind'>> | Partial<Omit<QQBotInput, 'kind'>>;
