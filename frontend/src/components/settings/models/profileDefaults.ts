import type { ModelInput, ModelKind, ProviderInput, RuntimeCatalogEntry } from '../../../types/models';

export const kinds: ModelKind[] = ['llm', 'embedding', 'reranker', 'image_embedding', 'vision', 'tts'];

export const newModel = (kind: ModelKind): ModelInput => ({
  name: '',
  alias: '',
  kind,
  model_ref: '',
  provider_profile_id: null,
  enabled: true,
  external_enabled: false,
  capabilities: { streaming: kind === 'llm', tools: false, vision: false, json_object: false, json_schema: false },
  parameters: kind === 'tts' ? { architecture: 'kokoro', speed: 1, response_format: 'mp3' }
    : kind === 'vision' ? { architecture: 'wd14', task: 'tags', batch_size: 1 } : {},
  lifecycle: { unload: 'manual', idle_seconds: 300 },
  runtime_id: kind === 'tts' ? 'python-worker' : null,
  runtime_variant: kind === 'tts' ? 'onnx-cpu' : null,
  runtime_options: kind === 'tts' ? { device: 'cpu', intraop_threads: 4, max_batch_size: 1 } : {},
});

export const runtimeFamilyKey = (runtimeId: string, variant: string) => runtimeId === 'llama-server' ? runtimeId : variant;
export const runtimeBuild = (variant: string) => variant === 'cpu' || variant === 'onnx-cpu' ? 'CPU' : 'CUDA';

export function selectManagedRuntime(value: ModelInput, entry: RuntimeCatalogEntry): ModelInput {
  if (!entry.supported || !entry.kinds.includes(value.kind) || entry.variant === 'infinity-cuda') {
    throw new Error('Unsupported runtime selection');
  }
  const properties = entry.options_schema.properties as Record<string, { default?: unknown }> | undefined;
  const runtime_options: ModelInput['runtime_options'] = {};
  for (const [key, property] of Object.entries(properties || {})) {
    if (typeof property.default === 'number' || typeof property.default === 'string') runtime_options[key] = property.default;
  }
  let parameters = { ...value.parameters };
  if (value.kind === 'tts') {
    const architecture = entry.variant === 'audio-cuda' ? 'chatterbox' : 'kokoro';
    parameters = architecture === value.parameters.architecture ? parameters : {
      architecture, speed: value.parameters.speed ?? 1, response_format: value.parameters.response_format ?? 'mp3',
    };
  }
  const capabilities = { ...value.capabilities, vision: false };
  if (entry.variant === 'transformers-cuda') {
    delete parameters.presence_penalty;
    delete parameters.frequency_penalty;
    capabilities.json_object = false;
    capabilities.json_schema = false;
  }
  return { ...value, provider_profile_id: null, runtime_id: entry.runtime_id, runtime_variant: entry.variant,
    runtime_options, parameters, capabilities };
}

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
