import type { ModelInput, ModelKind, ProviderInput } from '../../../types/models';

export const kinds: ModelKind[] = ['llm', 'embedding', 'reranker', 'image_embedding', 'vision'];

export const newModel = (kind: ModelKind): ModelInput => ({
  name: '',
  alias: '',
  kind,
  model_ref: '',
  provider_profile_id: null,
  enabled: true,
  external_enabled: false,
  capabilities: { streaming: kind === 'llm', tools: false, vision: false, json_object: false, json_schema: false },
  parameters: {},
  lifecycle: { unload: 'manual', idle_seconds: 300 },
  runtime_id: null,
  runtime_variant: null,
  runtime_options: {},
});

export const newProvider = (): ProviderInput => ({
  name: '',
  protocol: 'openai_compatible',
  base_url: 'http://127.0.0.1:1234/v1',
  timeout_seconds: 60,
  concurrency: 1,
  queue_size: 32,
  queue_timeout_seconds: 30,
  enabled: true,
});
