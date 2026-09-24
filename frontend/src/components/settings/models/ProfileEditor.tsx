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
import { FieldGroup, Field, FieldLabel, FieldDescription, FieldSet } from '@/components/ui/field';
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
import { useEffect, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import { useModelsStore } from '../../../store/useModelsStore';
import type { LocalModelSource, ModelInput, ModelInventoryItem } from '../../../types/models';

import type { ModelFeedbackProps } from './types';
import {
  kinds,
  localEngine,
  localSource,
  selectModelSource,
  sourceValue,
  updateModel,
} from './profileDefaults';
import { CudaLayersField } from './CudaLayersField';
import { PresetVoices } from './PresetVoices';

export type ProfileDraft = { id?: string; value: ModelInput };
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
  const activeView = useSettingsView();
  const { providers, profiles } = useModelsStore();
  const local = model?.value.source?.type === 'local' ? model.value.source : null;
  const engine = model ? localEngine(model.value) : null;
  const transformers = engine === 'transformers';
  const onnx = engine === 'kokoro' || engine === 'wd14';
  const audio = engine === 'chatterbox' || engine === 'qwen3tts';
  const [remoteModels, setRemoteModels] = useState<string[]>([]);
  const [inventory, setInventory] = useState<ModelInventoryItem[]>([]);
  const [discoveryError, setDiscoveryError] = useState('');
  const selectedSource = model ? sourceValue(model.value.source) : '';
  const modelKind = model?.value.kind;
  useEffect(() => {
    let cancelled = false;
    setRemoteModels([]);
    setInventory([]);
    setDiscoveryError('');
    const request =
      selectedSource === 'local'
        ? modelsApi.listModelInventory(modelKind).then((items) => {
            if (!cancelled) setInventory(items);
            return items.map((item) => item.model_ref);
          })
        : selectedSource.startsWith('provider:')
          ? modelsApi
              .listProviderModels(selectedSource.slice('provider:'.length))
              .then((value) => value.models)
          : null;
    if (request)
      void request
        .then((models) => {
          if (!cancelled) setRemoteModels(models);
        })
        .catch((error) => {
          if (!cancelled) setDiscoveryError(String(error.message));
        });
    return () => {
      cancelled = true;
    };
  }, [selectedSource, modelKind]);
  const patchModel = (patch: Partial<ModelInput>) =>
    setModel((draft) => (draft ? { ...draft, value: updateModel(draft.value, patch) } : null));
  const patchLocal = (patch: Partial<LocalModelSource>) =>
    setModel((draft) =>
      draft?.value.source?.type === 'local'
        ? { ...draft, value: updateModel(draft.value, { source: { ...draft.value.source, ...patch } }) }
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
              <FieldSet disabled={busy} className="model-form">
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
                      items={kinds.map((k) => ({ value: k, label: t('kinds.' + k) }))}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {kinds.map((k) => (
                          <SelectItem value={k} key={k}>
                            {t('kinds.' + k)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </Field>
                  <Field>
                    <FieldLabel>{t('source')}</FieldLabel>
                    <Select
                      value={selectedSource}
                      onValueChange={(nextSource) => {
                        const selected = nextSource ?? '';
                        setModel((draft) =>
                          draft
                            ? {
                                ...draft,
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
                                ),
                              }
                            : null,
                        );
                      }}
                      items={[
                        { value: '', label: t('unbound') },
                        ...(['llm', 'tts', 'vision'].includes(model.value.kind)
                          ? [{ value: 'local', label: t('localRuntime') }]
                          : []),
                        ...(['llm', 'embedding'].includes(model.value.kind) && providers.length
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
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="">{t('unbound')}</SelectItem>
                        {['llm', 'tts', 'vision'].includes(model.value.kind) ? (
                          <SelectGroup>
                            <SelectLabel>{t('localSourceGroup')}</SelectLabel>
                            <SelectItem value="local">{t('localRuntime')}</SelectItem>
                          </SelectGroup>
                        ) : null}
                        {['llm', 'embedding'].includes(model.value.kind) && providers.length ? (
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
                      items={remoteModels}
                      required
                      disabled={busy}
                      value={model.value.model_ref || null}
                      inputValue={model.value.model_ref}
                      onInputValueChange={(text, details) => {
                        if (details.reason === 'input-change') patchModel({ model_ref: text });
                      }}
                      onValueChange={(choice) => {
                        if (choice !== null) patchModel({ model_ref: choice });
                      }}
                    >
                      <ComboboxInput required aria-label={t('modelRef')} disabled={busy} />
                      <ComboboxContent>
                        <ComboboxEmpty>{t('common:noSuggestions')}</ComboboxEmpty>
                        <ComboboxList>
                          {(choice: string) => (
                            <ComboboxItem key={choice} value={choice}>
                              {choice}
                            </ComboboxItem>
                          )}
                        </ComboboxList>
                      </ComboboxContent>
                    </Combobox>
                    {model.value.kind === 'vision' ? (
                      <FieldDescription>{t('visionDirectoryHint')}</FieldDescription>
                    ) : null}
                  </Field>
                  <FieldGroup className="grid gap-4 sm:grid-cols-2">
                    <Field orientation="horizontal">
                      <Switch
                        checked={model.value.enabled}
                        onCheckedChange={(enabled) => patchModel({ enabled })}
                      />
                      <FieldLabel>{t('enabled')}</FieldLabel>
                    </Field>
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
                    {t('discoveryUnavailable')} {discoveryError}
                  </p>
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
                          disabled={onnx}
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
                          items={[
                            ...(onnx ? [] : [{ value: 'cuda', label: <>NVIDIA CUDA</> }]),
                            { value: 'cpu', label: <>CPU</> },
                          ]}
                        >
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {onnx ? null : <SelectItem value="cuda">NVIDIA CUDA</SelectItem>}
                            <SelectItem value="cpu">CPU</SelectItem>
                          </SelectContent>
                        </Select>
                      </Field>
                      {(engine === 'llama-server'
                        ? [
                            ['threads', 4, 1, 256],
                            ['context_size', 4096, 512, 1048576],
                            ['batch_size', 512, 1, 4096],
                          ]
                        : [['intraop_threads', 4, 1, 256]]
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
                  </>
                ) : null}
                {model.value.kind === 'llm' ? (
                  <>
                    <h3>{t('capabilities')}</h3>
                    <FieldGroup className="grid gap-4 sm:grid-cols-2">
                      {(Object.keys(model.value.capabilities) as Array<keyof ModelInput['capabilities']>).map(
                        (key) => (
                          <Field
                            key={key}
                            orientation="horizontal"
                            disabled={transformers && ['json_object', 'json_schema'].includes(key)}
                          >
                            <Switch
                              checked={model.value.capabilities[key]}
                              disabled={transformers && ['json_object', 'json_schema'].includes(key)}
                              onCheckedChange={(v) =>
                                patchModel({ capabilities: { ...model.value.capabilities, [key]: v } })
                              }
                            />
                            <FieldLabel>{t('cap.' + key)}</FieldLabel>
                          </Field>
                        ),
                      )}
                    </FieldGroup>
                    {engine === 'llama-server' && local && model.value.capabilities.vision ? (
                      <>
                        <Field>
                          <FieldLabel>{t('mmprojRef')}</FieldLabel>
                          <Combobox
                            items={
                              inventory.find((item) => item.model_ref === model.value.model_ref)
                                ?.mmproj_refs ?? []
                            }
                            required
                            disabled={busy}
                            value={String(local.execution_options.mmproj_ref ?? '') || null}
                            inputValue={String(local.execution_options.mmproj_ref ?? '')}
                            onInputValueChange={(text, details) => {
                              if (details.reason === 'input-change')
                                patchLocal({
                                  execution_options: { ...local.execution_options, mmproj_ref: text || null },
                                });
                            }}
                            onValueChange={(choice) => {
                              if (choice !== null)
                                patchLocal({
                                  execution_options: {
                                    ...local.execution_options,
                                    mmproj_ref: choice || null,
                                  },
                                });
                            }}
                          >
                            <ComboboxInput required aria-label={t('mmprojRef')} disabled={busy} />
                            <ComboboxContent>
                              <ComboboxEmpty>{t('common:noSuggestions')}</ComboboxEmpty>
                              <ComboboxList>
                                {(choice: string) => (
                                  <ComboboxItem key={choice} value={choice}>
                                    {choice}
                                  </ComboboxItem>
                                )}
                              </ComboboxList>
                            </ComboboxContent>
                          </Combobox>
                        </Field>

                        <p className="model-empty">{t('mmprojHint')}</p>
                      </>
                    ) : null}
                  </>
                ) : null}
                <h3>{t('parameters')}</h3>
                <ProfileParameters
                  value={model.value}
                  onChange={(parameters) => patchModel({ parameters })}
                />
                {audio ? <p className="model-empty">{t('ttsSeedHint')}</p> : null}
                {model.value.kind === 'tts' && model.value.parameters.architecture === 'chatterbox' ? (
                  <p className="model-empty">{t('chatterboxReferenceHint')}</p>
                ) : null}
                {model.value.kind === 'tts' && model.value.parameters.architecture === 'qwen3tts' ? (
                  <p className="model-empty">{t('qwenReferenceHint')}</p>
                ) : null}
                {local &&
                model.value.kind === 'tts' &&
                model.value.parameters.architecture === 'kokoro' &&
                model.id &&
                profiles.find((profile) => profile.id === model.id)?.parameters.architecture === 'kokoro' &&
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
              </FieldSet>
            </div>
            <DialogFooter>
              <Button disabled={busy} type="submit" variant="default">
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
