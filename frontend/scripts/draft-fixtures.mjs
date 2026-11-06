export const COGITA = '00000000-0000-4000-8000-000000000003';
export const USER = '00000000-0000-4000-8000-000000000004';
export const policy = { history_enabled: true, strategy: 'token_budget', message_window: { max_messages: 100 },
  include_attachments: 'explicit', compaction: { enabled: true, trigger_percent: 80, target_percent: 55, max_summary_tokens: null },
  retrieval: { trigger_percent: 80, target_percent: 55, max_checkpoint_tokens: null } };
export const normalCharacter = (id = COGITA) => ({ id, kind: 'normal', name: 'Cogita', system_prompt: '', persona_id: USER,
  created_at: '2026-09-25T00:00:00Z', updated_at: '2026-09-25T00:00:00Z', avatar_attachment_id: null, model_profile_id: 'model', temperature: null, reasoning: true, context_policy: policy,
  harness_enabled: false, tools_allowed: ['test_echo'], knowledge_base_ids: [], worldbook_ids: [] });
export function mockDraftCatalogs(api) {
  api.get = async (id) => normalCharacter(id);
  api.list = async () => [normalCharacter()];
  api.listSessions = async () => [];
  api.listPersonas = async () => [
    { id: USER, name: 'User', avatar_attachment_id: null, background: '', is_protected: true },
  ];
  api.listTools = async () => [{ name: 'test_echo', scope: 'general' }, { name: 'qq_send_message', scope: 'qqbot' }];
  api.listModelProfiles = async () => [{ id: 'model', kind: 'llm', enabled: true }];
  api.listProviderProfiles = async () => [];
  api.getModelSettings = async () => ({ default_model_profile_id: 'model' });
  api.getModelStatus = async () => ({ state: 'unloaded' });
}
