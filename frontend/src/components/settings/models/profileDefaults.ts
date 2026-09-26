import type { DirectoryInspection, ModelInput, ModelKind, ProviderInput, LocalEngine, LocalModelSource, ModelSource } from '../../../types/models';

export const kinds: ModelKind[] = ['llm', 'embedding', 'reranker', 'image_embedding', 'vision', 'tts', 'asr', 'processor'];
export const localOnly = (kind: ModelKind) => ['image_embedding', 'vision', 'tts', 'asr', 'processor'].includes(kind);

export const processorDefaults = { task: 'image_processing', style: 'natural', preset: 3,
  intensity: 1, tone: 1, structure: 1, skin: -1, auto_mask: false, channel_order: 'auto' };

export const localSource = (): LocalModelSource => ({
  type: 'local', execution_options: {}, lifecycle: { unload: 'manual', idle_seconds: 300 },
});

export const newModel = (kind: ModelKind): ModelInput => ({
  name: '',
  alias: '',
  kind,
  model_ref: '',
  source: kind === 'image_embedding' || kind === 'embedding' || kind === 'reranker' ? { ...localSource(), execution_options: { device: 'cuda', intraop_threads: 4, max_batch_size: 1 } }
    : kind === 'processor' ? { ...localSource(), execution_options: { device: 'd3d12', gpu_index: 0 } }
    : kind === 'asr' ? { ...localSource(), execution_options: { device: 'cuda', intraop_threads: 4 } }
    : kind === 'tts' || kind === 'vision' ? localSource() : null,
  enabled: true,
  external_enabled: false,
  capabilities: { streaming: kind === 'llm', tools: false, vision: false, json_object: false, json_schema: false },
  parameters: kind === 'tts' ? { speed: 1, response_format: 'mp3' }
    : kind === 'vision' ? { task: 'tags', thresholds: { general: 0.35, character: 0.85 } }
    : kind === 'image_embedding' ? { unload_other_tower_on_call: true }
    : kind === 'embedding' ? { query_prompt_name: null, document_prompt_name: null }
    : kind === 'asr' ? { language: 'auto', prompt: '', temperature: 0, response_format: 'json' }
    : kind === 'processor' ? { ...processorDefaults } : {},
});

export const ttsGenerationDefaults = {
  kokoro: {},
  chatterbox: { seed: null, exaggeration: 0.5, cfg_weight: 0.5, temperature: 0.8, repetition_penalty: 1.2, min_p: 0.05, top_p: 1 },
  qwen3tts: { seed: null, do_sample: true, temperature: 0.9, top_p: 1, top_k: 50, repetition_penalty: 1.05, max_new_tokens: 2048 },
};

export function localEngine(value: ModelInput, detected: LocalEngine | null = null): LocalEngine | null {
  if (value.source?.type !== 'local') return null;
  if (value.kind === 'image_embedding') return 'siglip2';
  if (value.kind === 'embedding') return 'sentence-transformers';
  if (value.kind === 'reranker') return 'cross-encoder';
  if (value.kind === 'asr') return 'whisper';
  if (value.kind === 'processor') return 'dlss5nr';
  return detected;
}

export function executionDefaults(engine: LocalEngine | null): LocalModelSource['execution_options'] {
  return engine === 'llama-server'
    ? { device: 'cuda', threads: 4, context_size: 4096, batch_size: 512, gpu_layers: 'auto' }
    : engine === 'dlss5nr' ? { device: 'd3d12', gpu_index: 0 }
    : engine === 'kokoro' || engine === 'wd14' ? { device: 'cpu', intraop_threads: 4, max_batch_size: 1 }
    : engine === 'siglip2' || engine === 'sentence-transformers' || engine === 'cross-encoder' ? { device: 'cuda', intraop_threads: 4, max_batch_size: 1 }
    : engine ? { device: 'cuda', intraop_threads: 4 } : {};
}

export function applyDirectoryInspection(value: ModelInput, information: DirectoryInspection,
  resetSettings: boolean, initializeVision: boolean): ModelInput {
  const engine = information.engine;
  if (value.source?.type !== 'local' || !engine) return value;
  let parameters = value.parameters;
  if (information.kind === 'tts') {
    const common = { speed: parameters.speed ?? 1, response_format: parameters.response_format ?? 'mp3' };
    parameters = { ...common, ...ttsGenerationDefaults[information.engine!], ...(resetSettings ? {} : parameters) };
  }
  const next = updateModel(value, { parameters, source: { ...value.source,
    execution_options: { ...executionDefaults(engine), ...(resetSettings ? {} : value.source.execution_options) },
  } }, engine);
  if (information.kind === 'llm' && engine === 'llama-server') {
    if (!information.mmproj_ref || initializeVision) next.capabilities = { ...next.capabilities,
      vision: !!information.mmproj_ref && !!information.main_model_ref };
  }
  return next;
}

export function updateModel(value: ModelInput, patch: Partial<ModelInput>, detected: LocalEngine | null = null): ModelInput {
  const next = { ...value, ...patch };
  const engine = localEngine(next, detected);
  if (next.source?.type === 'local' && engine !== localEngine(value, detected)) {
    next.source = { ...next.source, execution_options: executionDefaults(engine) };
  }
  if (engine === 'transformers') {
    next.parameters = { ...next.parameters };
    delete next.parameters.presence_penalty;
    delete next.parameters.frequency_penalty;
    next.capabilities = { ...next.capabilities, json_object: false, json_schema: false };
  }
  if (engine === 'sentence-transformers' && next.model_ref !== value.model_ref) {
    next.parameters = { query_prompt_name: null, document_prompt_name: null };
  }
  return next;
}

export function selectModelReference(value: ModelInput, model_ref: string, suggestName: boolean): ModelInput {
  return updateModel(value, { model_ref,
    ...(suggestName && !value.name.trim() && model_ref.trim()
      ? { name: model_ref.replace(/\/+$/, '').split('/').pop()! } : {}),
  });
}

export function sourceValue(source: ModelSource | null): string {
  return source?.type === 'provider' ? `provider:${source.provider_profile_id}` : source?.type ?? '';
}

export function selectModelSource(value: ModelInput, source: ModelSource | null): ModelInput {
  if (sourceValue(source) === sourceValue(value.source)) return value;
  const parameters = value.kind === 'embedding'
    ? source?.type === 'local' ? { query_prompt_name: null, document_prompt_name: null } : {}
    : value.parameters;
  if (!source) return { ...value, source: null, parameters };
  return updateModel(value, { source, parameters, model_ref: value.source ? '' : value.model_ref });
}

export const newProvider = (): ProviderInput => ({
  name: '', enabled: true,
  connection: {
    base_url: 'http://127.0.0.1:1234/v1', timeout_seconds: 60,
    concurrency: 1, queue_size: 32, queue_timeout_seconds: 30,
  },
});
