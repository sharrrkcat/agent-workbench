import type { ModelInput, ModelKind, ProviderInput, LocalEngine, LocalModelSource, ModelSource } from '../../../types/models';

export const kinds: ModelKind[] = ['llm', 'embedding', 'reranker', 'image_embedding', 'vision', 'tts'];

export const localSource = (): LocalModelSource => ({
  type: 'local', execution_options: {}, lifecycle: { unload: 'manual', idle_seconds: 300 },
});

export const newModel = (kind: ModelKind): ModelInput => ({
  name: '',
  alias: '',
  kind,
  model_ref: '',
  source: kind === 'tts' || kind === 'vision' ? { ...localSource(), execution_options: { device: 'cpu', intraop_threads: 4, max_batch_size: 1 } } : null,
  enabled: true,
  external_enabled: false,
  capabilities: { streaming: kind === 'llm', tools: false, vision: false, json_object: false, json_schema: false },
  parameters: kind === 'tts' ? { architecture: 'kokoro', speed: 1, response_format: 'mp3' }
    : kind === 'vision' ? { architecture: 'wd14', task: 'tags', thresholds: { general: 0.35, character: 0.85 } } : {},
});

export const ttsGenerationDefaults = {
  kokoro: {},
  chatterbox: { seed: null, exaggeration: 0.5, cfg_weight: 0.5, temperature: 0.8, repetition_penalty: 1.2, min_p: 0.05, top_p: 1 },
  qwen3tts: { seed: null, do_sample: true, temperature: 0.9, top_p: 1, top_k: 50, repetition_penalty: 1.05, max_new_tokens: 2048 },
};

export function selectTTSArchitecture(parameters: ModelInput['parameters'], architecture: keyof typeof ttsGenerationDefaults) {
  if (parameters.architecture === architecture) return { ...parameters };
  return { architecture, speed: parameters.speed ?? 1, response_format: parameters.response_format ?? 'mp3',
    ...ttsGenerationDefaults[architecture] };
}

export function localEngine(value: ModelInput): LocalEngine | null {
  if (value.source?.type !== 'local') return null;
  if (value.kind === 'llm') return value.model_ref.endsWith('.gguf') ? 'llama-server' : 'transformers';
  return value.kind === 'tts' || value.kind === 'vision' ? value.parameters.architecture as LocalEngine : null;
}

export function updateModel(value: ModelInput, patch: Partial<ModelInput>): ModelInput {
  const next = { ...value, ...patch };
  const engine = localEngine(next);
  if (next.source?.type === 'local' && engine !== localEngine(value)) {
    next.source = { ...next.source, execution_options: engine === 'llama-server'
      ? { device: 'cuda', threads: 4, context_size: 4096, batch_size: 512, gpu_layers: 'auto', mmproj_ref: null }
      : engine === 'kokoro' || engine === 'wd14' ? { device: 'cpu', intraop_threads: 4, max_batch_size: 1 }
      : { device: 'cuda', intraop_threads: 4 } };
  }
  if (engine === 'llama-server' && next.source?.type === 'local' &&
    (next.model_ref !== value.model_ref || !next.capabilities.vision)) {
    next.source = { ...next.source, execution_options: { ...next.source.execution_options, mmproj_ref: null } };
  }
  if (engine === 'transformers') {
    next.parameters = { ...next.parameters };
    delete next.parameters.presence_penalty;
    delete next.parameters.frequency_penalty;
    next.capabilities = { ...next.capabilities, json_object: false, json_schema: false };
  }
  return next;
}

export function sourceValue(source: ModelSource | null): string {
  return source?.type === 'provider' ? `provider:${source.provider_profile_id}` : source?.type ?? '';
}

export function selectModelSource(value: ModelInput, source: ModelSource | null): ModelInput {
  if (sourceValue(source) === sourceValue(value.source)) return value;
  if (!source) return { ...value, source: null };
  return updateModel(value, { source, model_ref: value.source ? '' : value.model_ref });
}

export const newProvider = (): ProviderInput => ({
  name: '', enabled: true,
  connection: {
    base_url: 'http://127.0.0.1:1234/v1', timeout_seconds: 60,
    concurrency: 1, queue_size: 32, queue_timeout_seconds: 30,
  },
});
