import type { ModelInput, ModelKind, ExternalBackendInput, LocalEngine } from '../../../types/models';

export const kinds: ModelKind[] = ['llm', 'embedding', 'reranker', 'image_embedding', 'vision', 'tts'];

export const newModel = (kind: ModelKind): ModelInput => ({
  name: '',
  alias: '',
  kind,
  model_ref: '',
  backend_profile_id: kind === 'tts' ? 'local' : null,
  enabled: true,
  external_enabled: false,
  capabilities: { streaming: kind === 'llm', tools: false, vision: false, json_object: false, json_schema: false },
  parameters: kind === 'tts' ? { architecture: 'kokoro', speed: 1, response_format: 'mp3' }
    : kind === 'vision' ? { architecture: 'wd14', task: 'tags', batch_size: 1 } : {},
  lifecycle: { unload: 'manual', idle_seconds: 300 },
  execution_options: kind === 'tts' ? { device: 'cpu', intraop_threads: 4, max_batch_size: 1 } : {},
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
  if (value.backend_profile_id !== 'local') return null;
  if (value.kind === 'llm') return value.model_ref.endsWith('.gguf') ? 'llama-server' : 'transformers';
  return value.kind === 'tts' ? value.parameters.architecture as LocalEngine : null;
}

export function updateModel(value: ModelInput, patch: Partial<ModelInput>): ModelInput {
  const next = { ...value, ...patch };
  const engine = localEngine(next);
  if (engine !== localEngine(value) || next.backend_profile_id !== value.backend_profile_id) {
    next.execution_options = engine === 'llama-server'
      ? { device: 'cuda', threads: 4, context_size: 4096, batch_size: 512, gpu_layers: 'auto' }
      : engine === 'kokoro' ? { device: 'cpu', intraop_threads: 4, max_batch_size: 1 }
      : engine ? { device: 'cuda', intraop_threads: 4 } : {};
  }
  if (engine === 'llama-server' || engine === 'transformers') next.capabilities = { ...next.capabilities, vision: false };
  if (engine === 'transformers') {
    next.parameters = { ...next.parameters };
    delete next.parameters.presence_penalty;
    delete next.parameters.frequency_penalty;
    next.capabilities = { ...next.capabilities, json_object: false, json_schema: false };
  }
  return next;
}

export const newBackend = (): ExternalBackendInput => ({
  name: '', type: 'openai_compatible', enabled: true, download: null,
  connection: {
    base_url: 'http://127.0.0.1:1234/v1', timeout_seconds: 60,
    concurrency: 1, queue_size: 32, queue_timeout_seconds: 30,
  },
});
