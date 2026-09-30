export function mockDraftCatalogs(api) {
  api.listPersonas = async () => [
    { id: 'user', collection: 'user', name: 'User', avatar_attachment_id: null },
    { id: 'agent', collection: 'agent', name: 'Cogita', is_protected: true },
  ];
  api.listTools = async () => [{ name: 'base64_encode' }];
  api.listModelProfiles = async () => [{ id: 'model', kind: 'llm', enabled: true }];
  api.listProviderProfiles = async () => [];
  api.getModelSettings = async () => ({ default_model_profile_id: 'model' });
  api.getModelStatus = async () => ({ state: 'unloaded' });
}
