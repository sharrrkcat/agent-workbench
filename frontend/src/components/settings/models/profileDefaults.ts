import type { DirectoryInspection, ModelInput, ModelKind, ProviderInput, LocalEngine, LocalModelSource, ModelSource } from '../../../types/models';

export const localOnly = (kind: ModelKind) => ['image_embedding', 'vision', 'asr', 'processor', 'reranker'].includes(kind);

export const grokVoices = ['alloy', 'echo', 'fable', 'onyx', 'nova', 'eve', 'sal', 'rex'];

export function selectTTSArchitecture(parameters: ModelInput['parameters'], architecture: 'grok-voice-latest' | 'customize') {
  return { ...parameters, architecture,
    voice: architecture === 'customize' || grokVoices.includes(String(parameters.voice)) ? parameters.voice : 'alloy' };
}

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
  source: kind === 'image_generation' ? null
    : kind === 'image_embedding' || kind === 'embedding' || kind === 'reranker' ? { ...localSource(), execution_options: { device: 'cuda', intraop_threads: 4, max_batch_size: 1 } }
    : kind === 'processor' ? { ...localSource(), execution_options: { device: 'd3d12', gpu_index: 0 } }
    : kind === 'asr' ? { ...localSource(), execution_options: { device: 'cuda', intraop_threads: 4 } }
    : kind === 'llm' ? { ...localSource(), execution_options: { context_size: 4096 } } : localSource(),
  enabled: true,
  external_enabled: false,
  context_window_tokens: null,
  request_options: kind === 'llm' ? { streaming: true, skip_tool_capability_check: false, skip_vision_capability_check: false,
    skip_instant_capability_check: false, skip_reasoning_capability_check: false } : null,
  parameters: kind === 'tts' ? { speed: 1, response_format: 'mp3' }
    : kind === 'vision' ? { task: 'tags', thresholds: { general: 0.35, character: 0.85 } }
    : kind === 'image_embedding' ? { unload_other_tower_on_call: true }
    : kind === 'embedding' ? { query_prompt_name: null, document_prompt_name: null }
    : kind === 'asr' ? { language: 'auto', prompt: '', temperature: 0, response_format: 'json' }
    : kind === 'processor' ? { ...processorDefaults }
    : kind === 'image_generation' ? { n: 1 } : {},
});

export function selectModelKind(value: ModelInput, kind: ModelKind): ModelInput {
  if (value.kind === kind) return value;
  return { ...newModel(kind), name: value.name, alias: value.alias, external_enabled: value.external_enabled };
}

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
    : engine === 'transformers' ? { device: 'cuda', intraop_threads: 4, context_size: 4096 }
    : engine === 'dlss5nr' ? { device: 'd3d12', gpu_index: 0 }
    : engine === 'kokoro' || engine === 'wd14' ? { device: 'cpu', intraop_threads: 4, max_batch_size: 1 }
    : engine === 'siglip2' || engine === 'sentence-transformers' || engine === 'cross-encoder' ? { device: 'cuda', intraop_threads: 4, max_batch_size: 1 }
    : engine ? { device: 'cuda', intraop_threads: 4 } : {};
}

export function applyDirectoryInspection(value: ModelInput, information: DirectoryInspection,
  resetSettings: boolean): ModelInput {
  const engine = information.engine;
  if (value.source?.type !== 'local' || !engine) return value;
  let parameters = value.parameters;
  if (information.kind === 'tts') {
    const common = { speed: parameters.speed ?? 1, response_format: parameters.response_format ?? 'mp3' };
    parameters = { ...common, ...ttsGenerationDefaults[information.engine!], ...(resetSettings ? {} : parameters) };
  }
  const next = updateModel(value, { parameters, source: { ...value.source,
    execution_options: { ...executionDefaults(engine), ...(resetSettings ? {} : value.source.execution_options),
      ...(value.kind === 'llm' && 'context_size' in value.source.execution_options
        ? { context_size: value.source.execution_options.context_size } : {}),
    },
  } }, engine);
  return next;
}

export function updateModel(value: ModelInput, patch: Partial<ModelInput>, detected: LocalEngine | null = null): ModelInput {
  const next = { ...value, ...patch };
  if (next.kind !== 'llm' || next.source?.type === 'local') next.context_window_tokens = null;
  const engine = localEngine(next, detected);
  if (next.source?.type === 'local' && engine !== localEngine(value, detected)) {
    next.source = { ...next.source, execution_options: { ...executionDefaults(engine),
      ...(next.kind === 'llm' && 'context_size' in next.source.execution_options
        ? { context_size: next.source.execution_options.context_size } : {}),
    } };
  }
  if (engine === 'transformers') {
    next.parameters = { ...next.parameters };
    delete next.parameters.presence_penalty;
    delete next.parameters.frequency_penalty;
  }
  if (engine === 'sentence-transformers' && next.model_ref !== value.model_ref) {
    next.parameters = { query_prompt_name: null, document_prompt_name: null };
  }
  return next;
}

export function selectModelReference(value: ModelInput, model_ref: string, suggestIdentity: boolean): ModelInput {
  const reference = model_ref.trim();
  return updateModel(value, { model_ref,
    ...(suggestIdentity && reference ? {
      ...(!value.name.trim() ? { name: reference } : {}),
      ...(!value.alias.trim() ? { alias: reference.toLowerCase().replace(/[^a-z0-9._-]+/g, '-')
        .replace(/^[^a-z0-9]+/, '').slice(0, 128) } : {}),
    } : {}),
  });
}

export function sourceValue(source: ModelSource | null): string {
  return source?.type === 'provider' ? `provider:${source.provider_profile_id}` : source?.type ?? '';
}

export function selectModelSource(value: ModelInput, source: ModelSource | null, newDraft = false): ModelInput {
  if (sourceValue(source) === sourceValue(value.source)) return value;
  const parameters = value.kind === 'embedding'
    ? source?.type === 'local' ? { query_prompt_name: null, document_prompt_name: null } : {}
    : value.kind === 'tts' ? { speed: value.parameters.speed ?? 1, response_format: value.parameters.response_format ?? 'mp3',
        ...(source?.type === 'provider' ? { architecture: 'grok-voice-latest', voice: 'alloy' } : {}) }
    : value.parameters;
  const request_options = value.request_options ? { ...value.request_options,
    skip_tool_capability_check: false, skip_vision_capability_check: false,
    skip_instant_capability_check: false, skip_reasoning_capability_check: false } : null;
  if (!source) return { ...value, source: null, parameters, request_options };
  const context = value.source?.type === 'local'
    ? value.source.execution_options.context_size : value.context_window_tokens;
  const contextWindow = newDraft && value.kind === 'llm'
    ? context ?? (source.type === 'local' ? 4096 : 258000) : undefined;
  return updateModel(value, {
    source: source.type === 'local' && contextWindow !== undefined
      ? { ...source, execution_options: { ...source.execution_options, context_size: contextWindow } } : source,
    ...(source.type === 'provider' && contextWindow !== undefined ? { context_window_tokens: Number(contextWindow) } : {}),
    parameters, request_options, model_ref: value.source ? '' : value.model_ref,
  });
}

export const newProvider = (): Omit<ProviderInput, 'enabled'> => ({
  name: '',
  connection: {
    base_url: 'http://127.0.0.1:1234/v1', timeout_seconds: 60,
    allow_unindexed_complete_tool_call: false,
    concurrency: 1, queue_size: 32, queue_timeout_seconds: 30,
  },
});
