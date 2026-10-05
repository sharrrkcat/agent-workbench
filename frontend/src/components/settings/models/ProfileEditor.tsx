import { useSettingsView } from '../SettingsView';
import {
  Combobox,
  ComboboxInput,
  ComboboxContent,
  ComboboxList,
  ComboboxItem,
  ComboboxEmpty,
} from '@/components/ui/combobox';
import { Input } from '@/components/ui/input';
import { FieldGroup, Field, FieldLabel, FieldDescription, FieldSet, FieldLegend } from '@/components/ui/field';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
  SelectGroup,
  SelectLabel,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { ProfileParameters } from './ProfileParameters';
import { Save } from 'lucide-react';
import { useEffect, useId, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import { useModelsStore } from '../../../store/useModelsStore';
import { modelKinds } from '../../../types/models';
import type { DirectoryInspection, LocalEmbeddingParameters, LocalEngine, LocalModelSource, ModelInput } from '../../../types/models';

import type { ModelFeedbackProps } from './types';
import {
  applyDirectoryInspection,
  localEngine,
  localOnly,
  localSource,
  selectModelSource,
  selectModelReference,
  sourceValue,
  updateModel,
} from './profileDefaults';
import { CudaLayersField } from './CudaLayersField';
import { PresetVoices } from './PresetVoices';
import { SiglipInspectionPanel } from './SiglipInspection';
import { TextEmbeddingInspectionPanel } from './TextEmbeddingInspection';
import { RerankerInspectionPanel } from './RerankerInspection';
import { ASRInspectionPanel } from './ASRInspection';
import { DirectoryInspectionPanel } from './DirectoryInspection';

export type ProfileDraft = {
  id?: string; value: ModelInput; detectedEngine?: LocalEngine;
  directory?: { ref: string; kind: string; information?: DirectoryInspection; error?: string };
};
export function ProfileEditor({
  model,
  setModel,
  run,
  busy,
  feedback,
}: ModelFeedbackProps & {
  model: ProfileDraft | null;
  setModel: Dispatch<SetStateAction<ProfileDraft | null>>;
}) {
  const { t } = useTranslation('llm');
  const formId = useId();
  const activeView = useSettingsView();
  const { providers, profiles } = useModelsStore();
  const local = model?.value.source?.type === 'local' ? model.value.source : null;
  const directory = model && local && model.directory?.ref === model.value.model_ref
    && model?.directory?.kind === model?.value.kind ? model.directory : undefined;
  const information = directory?.information;
  const engine = model ? localEngine(model.value, information?.engine ?? null) : null;
  const transformers = engine === 'transformers';
  const onnx = engine === 'kokoro' || engine === 'wd14';
  const audio = engine === 'chatterbox' || engine === 'qwen3tts';
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);
  const [discoveryError, setDiscoveryError] = useState('');
  const selectedSource = model ? sourceValue(model.value.source) : '';
  const modelKind = model?.value.kind;
  const modelRef = model?.value.model_ref ?? '';
  const modelID = model?.id;
  const opened = !!model;
  const savedReference = profiles.find((profile) => profile.id === modelID)?.model_ref;
  useEffect(() => {
    if (!opened || selectedSource !== 'local' || !modelRef.trim()
      || modelKind !== 'llm' && modelKind !== 'tts' && modelKind !== 'vision' && modelKind !== 'processor') return;
    let cancelled = false;
    void modelsApi.inspectLocalDirectory(modelKind, modelRef).then((information) => {
      if (cancelled) return;
      setModel((draft) => {
        if (!draft || draft.id !== modelID || draft.value.model_ref !== modelRef
          || draft.value.kind !== modelKind || draft.value.source?.type !== 'local') return draft;
        const resetSettings = draft.detectedEngine !== undefined
          ? draft.detectedEngine !== information.engine : !draft.id || savedReference !== modelRef;
        return { ...draft,
          value: applyDirectoryInspection(draft.value, information, resetSettings),
          detectedEngine: information.engine ?? draft.detectedEngine,
          directory: { ref: modelRef, kind: modelKind, information },
        };
      });
    }).catch((error) => {
      if (!cancelled) setModel((draft) => draft && draft.id === modelID
        && draft.value.model_ref === modelRef && draft.value.kind === modelKind && draft.value.source?.type === 'local'
        ? { ...draft, directory: { ref: modelRef, kind: modelKind, error: String(error.message) } } : draft);
    });
    return () => { cancelled = true; };
  }, [opened, selectedSource, modelKind, modelRef, modelID, savedReference, setModel]);
  useEffect(() => {
    let cancelled = false;
    setSuggestions([]);
    setDiscoveryError('');
    setSuggestionsLoading(false);
    if (!opened || !activeView) return;
    const request =
      selectedSource === 'local'
        ? modelsApi.listModelInventory(modelKind).then((items) => items.map((item) => item.model_ref))
        : selectedSource.startsWith('provider:')
          ? modelsApi
              .listProviderModels(selectedSource.slice('provider:'.length))
              .then((value) => value.models)
          : null;
    if (request) {
      setSuggestionsLoading(true);
      void request
        .then((models) => {
          if (!cancelled) setSuggestions(models);
        })
        .catch((error) => {
          if (!cancelled) setDiscoveryError(String(error.message));
        })
        .finally(() => {
          if (!cancelled) setSuggestionsLoading(false);
        });
    }
    return () => {
      cancelled = true;
    };
  }, [opened, activeView, selectedSource, modelKind]);
  const suggestionsMessage = !selectedSource ? t('selectModelSource')
    : suggestionsLoading ? t('referenceSuggestions.loading')
    : discoveryError ? t(selectedSource === 'local' ? 'referenceSuggestions.localUnavailable' : 'discoveryUnavailable')
    : suggestions.length ? t('referenceSuggestions.noMatch')
    : t(selectedSource === 'local' ? 'referenceSuggestions.noDirectories' : 'referenceSuggestions.noModels');
  const patchModel = (patch: Partial<ModelInput>) =>
    setModel((draft) => (draft ? { ...draft, value: updateModel(draft.value, patch, engine),
    } : null));
  const patchReference = (modelRef: string, suggestName = false) => setModel((draft) => draft ? {
    ...draft, value: selectModelReference(draft.value, modelRef,
      suggestName && !draft.id),
  } : null);
  const patchLocal = (patch: Partial<LocalModelSource>) =>
    setModel((draft) =>
      draft?.value.source?.type === 'local'
        ? { ...draft, value: updateModel(draft.value, { source: { ...draft.value.source, ...patch } }, engine) }
        : draft,
    );
  return (
    <Dialog
      open={activeView && !!model}
      onOpenChange={(open) => {
        if (!open)
          (() => {
            if (!busy) setModel(null);
          })();
      }}
    >
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{model?.id ? t('editModel') : t('addModel')}</DialogTitle>
        </DialogHeader>
        {model ? (
          <form
            className="settings-dialog-form"
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                if (model.id) await modelsApi.patchModelProfile(model.id, model.value);
                else await modelsApi.createModelProfile(model.value);
                setModel(null);
              });
            }}
          >
            <div className="settings-dialog-body">
              {feedback}
              <FieldSet disabled={busy} className="block">
                <FieldGroup className="model-form">
                <FieldGroup className="grid gap-4 sm:grid-cols-2">
                  <Field>
                    <FieldLabel>{t('name')}</FieldLabel>
                    <Input
                      required
                      value={model.value.name}
                      onChange={(e) => patchModel({ name: e.target.value })}
                    />
                  </Field>
                  <Field>
                    <FieldLabel>{t('alias')}</FieldLabel>
                    <Input
                      required
                      pattern="[a-z0-9][a-z0-9._-]{0,127}"
                      value={model.value.alias}
                      onChange={(e) => patchModel({ alias: e.target.value })}
                    />
                  </Field>
                  <Field>
                    <FieldLabel>{t('kind')}</FieldLabel>
                    <Select
                      value={model.value.kind}
                      disabled={true}
                      items={modelKinds.map((k) => ({ value: k, label: t('kinds.' + k) }))}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectGroup>
                        {modelKinds.map((k) => (
                          <SelectItem value={k} key={k}>
                            {t('kinds.' + k)}
                          </SelectItem>
                        ))}
                        </SelectGroup>
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field>
                    <FieldLabel>{t('source')}</FieldLabel>
                    <Select
                      value={selectedSource || null}
                      required
                      disabled={localOnly(model.value.kind) && !!local}
                      onValueChange={(nextSource) => {
                        if (!nextSource) return;
                        const selected = nextSource ?? '';
                        setModel((draft) =>
                          draft
                            ? {
                                ...draft,
                                ...(selected !== selectedSource ? { directory: undefined, detectedEngine: undefined } : {}),
                                value: selectModelSource(
                                  draft.value,
                                  selected === 'local'
                                    ? localSource()
                                    : selected
                                      ? {
                                          type: 'provider',
                                          provider_profile_id: selected.slice('provider:'.length),
                                        }
                                      : null,
                                  !draft.id,
                                ),
                              }
                            : null,
                        );
                      }}
                      items={[
                        ...(['llm', 'tts', 'vision', 'image_embedding', 'embedding', 'reranker', 'asr', 'processor'].includes(model.value.kind)
                          ? [{ value: 'local', label: t('localRuntime') }]
                          : []),
                        ...(['llm', 'embedding', 'tts'].includes(model.value.kind) && providers.length
                          ? providers.map((provider) => ({
                              value: `provider:${provider.id}`,
                              label: (
                                <>
                                  {provider.name}
                                  {provider.enabled ? '' : ` (${t('disabled')})`}
                                </>
                              ),
                            }))
                          : []),
                      ]}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder={t('selectModelSource')} />
                      </SelectTrigger>
                      <SelectContent>
                        {['llm', 'tts', 'vision', 'image_embedding', 'embedding', 'reranker', 'asr', 'processor'].includes(model.value.kind) ? (
                          <SelectGroup>
                            <SelectLabel>{t('localSourceGroup')}</SelectLabel>
                            <SelectItem value="local">{t('localRuntime')}</SelectItem>
                          </SelectGroup>
                        ) : null}
                        {['llm', 'embedding', 'tts'].includes(model.value.kind) && providers.length ? (
                          <SelectGroup>
                            <SelectLabel>{t('providers')}</SelectLabel>
                            {providers.map((provider) => (
                              <SelectItem value={`provider:${provider.id}`} key={provider.id}>
                                {provider.name}
                                {provider.enabled ? '' : ` (${t('disabled')})`}
                              </SelectItem>
                            ))}
                          </SelectGroup>
                        ) : null}
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field>
                    <FieldLabel>{t('modelRef')}</FieldLabel>
                    <Combobox
                      items={suggestions}
                      required
                      disabled={busy}
                      value={model.value.model_ref || null}
                      inputValue={model.value.model_ref}
                      onInputValueChange={(text, details) => {
                        if (details.reason === 'input-change') patchReference(text);
                      }}
                      onValueChange={(choice) => {
                        if (choice !== null) patchReference(choice, true);
                      }}
                    >
                      <ComboboxInput required aria-label={t('modelRef')} disabled={busy}
                        onBlur={() => setModel((draft) => draft ? { ...draft,
                          value: selectModelReference(draft.value, draft.value.model_ref,
                            !draft.id),
                        } : null)} />
                      <ComboboxContent>
                        <ComboboxEmpty>{suggestionsMessage}</ComboboxEmpty>
                        <ComboboxList>
                          {(choice: string) => (
                            <ComboboxItem key={choice} value={choice}>
                              {choice}
                            </ComboboxItem>
                          )}
                        </ComboboxList>
                      </ComboboxContent>
                    </Combobox>
                    {model.value.kind === 'processor' ? <FieldDescription>{t('processor.directoryHint')}</FieldDescription> : null}
                    {model.value.kind === 'vision' ? (
                      <FieldDescription>{t('visionDirectoryHint')}</FieldDescription>
                    ) : null}
                    {local && (model.value.kind === 'llm' || model.value.kind === 'tts') ? (
                      <FieldDescription>{t('directory.referenceHint')}</FieldDescription>
                    ) : null}
                    {model.value.kind === 'image_embedding' ? (
                      <FieldDescription>{t('siglip.directoryHint')}</FieldDescription>
                    ) : null}
                    {model.value.kind === 'embedding' && local ? (
                      <FieldDescription>{t('textEmbedding.directoryHint')}</FieldDescription>
                    ) : null}
                    {model.value.kind === 'reranker' && local ? (
                      <FieldDescription>{t('reranker.directoryHint')}</FieldDescription>
                    ) : null}
                    {model.value.kind === 'asr' && local ? (
                      <FieldDescription>{t('asr.directoryHint')}</FieldDescription>
                    ) : null}
                  </Field>
                  <FieldGroup className="grid gap-4 sm:grid-cols-2">
                    <Field orientation="horizontal">
                      <Switch
                        checked={model.value.external_enabled}
                        onCheckedChange={(external_enabled) => patchModel({ external_enabled })}
                      />
                      <FieldLabel>{t('externalModel')}</FieldLabel>
                    </Field>
                  </FieldGroup>
                </FieldGroup>
                {model.value.source?.type === 'provider' ? (
                  <p className="model-empty">{t('providerModelHint')}</p>
                ) : null}
                {discoveryError ? (
                  <p role="status" className="model-empty">
                    {t(local ? 'referenceSuggestions.localUnavailable' : 'discoveryUnavailable')} {discoveryError}
                  </p>
                ) : null}
                {model.value.kind === 'image_embedding' && local && model.value.model_ref.trim() ? (
                  <SiglipInspectionPanel key={model.value.model_ref} modelRef={model.value.model_ref} />
                ) : null}
                {model.value.kind === 'reranker' && local && model.value.model_ref.trim() ? (
                  <RerankerInspectionPanel key={model.value.model_ref} modelRef={model.value.model_ref} />
                ) : null}
                {model.value.kind === 'asr' && local && model.value.model_ref.trim() ? (
                  <ASRInspectionPanel key={model.value.model_ref} modelRef={model.value.model_ref} />
                ) : null}
                {local && modelRef.trim() && ['llm', 'tts', 'vision', 'processor'].includes(model.value.kind) ? (
                  <DirectoryInspectionPanel information={information} error={directory?.error} />
                ) : null}
                {model.value.kind === 'embedding' && local && model.value.model_ref.trim() ? (
                  <TextEmbeddingInspectionPanel key={model.value.model_ref} modelRef={model.value.model_ref}
                    parameters={{ query_prompt_name: null, document_prompt_name: null,
                      ...model.value.parameters } as LocalEmbeddingParameters}
                    onChange={(parameters) => patchModel({ parameters })} />
                ) : null}
                {engine && local ? (
                  <>
                    <h3>{t('executionOptions')}</h3>
                    <p className="model-empty">
                      {t('engine')}: {t('engines.' + engine)}
                    </p>
                    <FieldGroup className="grid gap-4 sm:grid-cols-2">
                      <Field>
                        <FieldLabel>{t('runtimeDevice')}</FieldLabel>
                        <Select
                          value={String(local.execution_options.device)}
                          disabled={onnx || engine === 'dlss5nr'}
                          onValueChange={(selected) =>
                            patchLocal({
                              execution_options: {
                                ...local.execution_options,
                                device: selected ?? '',
                                ...(engine === 'llama-server'
                                  ? { gpu_layers: (selected ?? '') === 'cpu' ? 0 : 'auto' }
                                  : {}),
                              },
                            })
                          }
                          items={engine === 'dlss5nr' ? [{ value: 'd3d12', label: 'NVIDIA D3D12' }] : [
                            ...(onnx ? [] : [{ value: 'cuda', label: <>NVIDIA CUDA</> }]),
                            { value: 'cpu', label: <>CPU</> },
                          ]}
                        >
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent><SelectGroup>
                            {engine === 'dlss5nr' ? <SelectItem value="d3d12">NVIDIA D3D12</SelectItem> : <>
                              {onnx ? null : <SelectItem value="cuda">NVIDIA CUDA</SelectItem>}
                              <SelectItem value="cpu">CPU</SelectItem>
                            </>}
                          </SelectGroup></SelectContent>
                        </Select>
                      </Field>
                      {(engine === 'llama-server'
                        ? [
                            ['threads', 4, 1, 256],
                            ['batch_size', 512, 1, 4096],
                          ]
                        : engine === 'siglip2' || engine === 'sentence-transformers' || engine === 'cross-encoder' ? [['intraop_threads', 4, 1, 256], ['max_batch_size', 1, 1, 16]]
                        : engine === 'dlss5nr' ? [['gpu_index', 0, 0, 15]] : [['intraop_threads', 4, 1, 256]]
                      ).map(([key, initial, min, max]) => (
                        <Field key={String(key)}>
                          <FieldLabel>{t('runtimeParams.' + key)}</FieldLabel>
                          <Input
                            type="number"
                            min={Number(min)}
                            max={Number(max)}
                            step={1}
                            value={
                              Number.isNaN(Number(local.execution_options[String(key)] ?? initial))
                                ? ''
                                : (Number(local.execution_options[String(key)] ?? initial) ?? '')
                            }
                            onChange={(event) =>
                              patchLocal({
                                execution_options: {
                                  ...local.execution_options,
                                  [String(key)]:
                                    event.currentTarget.value === ''
                                      ? Number(initial)
                                      : Number(event.currentTarget.value),
                                },
                              })
                            }
                          />
                        </Field>
                      ))}
                      {engine === 'llama-server' && local.execution_options.device === 'cuda' ? (
                        <CudaLayersField
                          value={
                            typeof local.execution_options.gpu_layers === 'number'
                              ? local.execution_options.gpu_layers
                              : 'auto'
                          }
                          onChange={(gpu_layers) =>
                            patchLocal({ execution_options: { ...local.execution_options, gpu_layers } })
                          }
                        />
                      ) : null}
                    </FieldGroup>
                    {transformers ? <p className="model-empty">{t('transformersDeviceHint')}</p> : null}
                    {audio ? <p className="model-empty">{t('audioDeviceHint')}</p> : null}
                    {engine === 'siglip2' ? <p className="model-empty">{t('siglip.deviceHint')}</p> : null}
                    {engine === 'sentence-transformers' || engine === 'cross-encoder' ? <p className="model-empty">{t('textEmbedding.deviceHint')}</p> : null}
                  </>
                ) : null}
                {model.value.kind === 'llm' && model.value.request_options ? (
                  <FieldGroup>
                    <Field orientation="horizontal">
                      <Switch checked={model.value.request_options.streaming}
                        onCheckedChange={(streaming) => patchModel({ request_options: { ...model.value.request_options!, streaming } })} />
                      <FieldLabel>{t('requestOptions.streaming')}</FieldLabel>
                    </Field>
                    {local ? (['skip_tool_capability_check', 'skip_vision_capability_check'] as const).map((key) => (
                      <Field key={key} orientation="horizontal">
                        <Switch checked={model.value.request_options![key]}
                          onCheckedChange={(value) => patchModel({ request_options: { ...model.value.request_options!, [key]: value } })} />
                        <FieldLabel>{t('requestOptions.' + key)}</FieldLabel>
                      </Field>
                    )) : null}
                    {local ? <p className="text-xs text-muted-foreground">{t('requestOptions.help')}</p> : null}
                    {local ? <FieldSet>
                      <FieldLegend>{t('requestOptions.reasoningPreflight')}</FieldLegend>
                      <p id={formId + '-reasoning-help'} className="text-xs leading-normal text-muted-foreground">{t('requestOptions.reasoningHelp')}</p>
                      {(['skip_instant_capability_check', 'skip_reasoning_capability_check'] as const).map((key) => (
                        <Field key={key} orientation="horizontal">
                          <Switch id={formId + key} aria-describedby={formId + '-reasoning-help'} checked={model.value.request_options![key]}
                            onCheckedChange={(value) => patchModel({ request_options: { ...model.value.request_options!, [key]: value } })} />
                          <FieldLabel htmlFor={formId + key}>{t('requestOptions.' + key)}</FieldLabel>
                        </Field>
                      ))}
                    </FieldSet> : null}
                  </FieldGroup>
                ) : null}
                {engine !== 'sentence-transformers' && model.value.kind !== 'reranker' ? <>
                  <h3>{t('parameters')}</h3>
                  {model.value.kind === 'llm' ? <Field>
                    <FieldLabel htmlFor={formId + '-context-window'}>{t('contextWindow')}</FieldLabel>
                    <Input id={formId + '-context-window'} type="number" required={!model.id} min={512} max={local ? 1048576 : undefined} step={1}
                      value={(local ? local.execution_options.context_size ?? (model.id ? 4096 : '') : model.value.context_window_tokens) ?? ''}
                      onChange={(event) => {
                        const value = event.currentTarget.value === '' ? null : Number(event.currentTarget.value);
                        if (local) patchLocal({ execution_options: { ...local.execution_options, context_size: value ?? (model.id ? 4096 : null) } });
                        else patchModel({ context_window_tokens: value });
                      }} />
                    <FieldDescription>{t(local ? 'contextWindowLocalHelp' : 'contextWindowProviderHelp')}{!model.id ? ` ${t('contextWindowCreateHelp')}` : ''}</FieldDescription>
                  </Field> : null}
                  <ProfileParameters value={model.value} engine={engine} onChange={(parameters) => patchModel({ parameters })} />
                  {model.value.kind === 'llm' ? <p className="model-empty">{t('outputReserveHelp')}</p> : null}
                </> : null}
                {audio ? <p className="model-empty">{t('ttsSeedHint')}</p> : null}
                {engine === 'chatterbox' ? (
                  <p className="model-empty">{t('chatterboxReferenceHint')}</p>
                ) : null}
                {engine === 'qwen3tts' ? (
                  <p className="model-empty">{t('qwenReferenceHint')}</p>
                ) : null}
                {local &&
                model.value.kind === 'tts' &&
                engine === 'kokoro' &&
                model.id &&
                profiles.find((profile) => profile.id === model.id)?.model_ref === model.value.model_ref ? (
                  <PresetVoices profileId={model.id} />
                ) : null}
                {local ? (
                  <>
                    <h3>{t('lifecycle')}</h3>
                    <FieldGroup className="grid gap-4 sm:grid-cols-2">
                      <Field>
                        <FieldLabel>{t('release')}</FieldLabel>
                        <Select
                          value={local.lifecycle.unload}
                          onValueChange={(selected) =>
                            patchLocal({
                              lifecycle: {
                                ...local.lifecycle,
                                unload: (selected ?? '') as LocalModelSource['lifecycle']['unload'],
                              },
                            })
                          }
                          items={(['manual', 'after_request', 'idle'] as const).map((v) => ({
                            value: v,
                            label: t('policy.' + v),
                          }))}
                        >
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {(['manual', 'after_request', 'idle'] as const).map((v) => (
                              <SelectItem value={v} key={v}>
                                {t('policy.' + v)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </Field>
                      {local.lifecycle.unload === 'idle' ? (
                        <Field>
                          <FieldLabel>{t('idleSeconds')}</FieldLabel>
                          <Input
                            type="number"
                            min={1}
                            step={1}
                            value={
                              Number.isNaN(local.lifecycle.idle_seconds)
                                ? ''
                                : (local.lifecycle.idle_seconds ?? '')
                            }
                            onChange={(event) =>
                              patchLocal({
                                lifecycle: {
                                  ...local.lifecycle,
                                  idle_seconds:
                                    event.currentTarget.value === ''
                                      ? 300
                                      : Number(event.currentTarget.value),
                                },
                              })
                            }
                          />
                        </Field>
                      ) : null}
                    </FieldGroup>
                  </>
                ) : null}
                </FieldGroup>
              </FieldSet>
            </div>
            <DialogFooter>
              <Button disabled={busy || !model.value.source} type="submit" variant="default">
                <Save data-icon="inline-start" />
                {t('save')}
              </Button>
            </DialogFooter>
          </form>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
