import { ProfileParameters } from './ProfileParameters';
import { Save } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import { useModelsStore } from '../../../store/useModelsStore';
import type { ModelInput } from '../../../types/models';
import { AppModal } from '../../ui/AppModal';
import { Field, Check, NumberInput } from './fields';
import type { ModelFeedbackProps } from './types';
import { kinds, runtimeFamilyKey, runtimeBuild, selectManagedRuntime } from './profileDefaults';
import { CudaLayersField } from './CudaLayersField';
import { PresetVoices } from './PresetVoices';

export type ProfileDraft = { id?: string; value: ModelInput };
export function ProfileEditor({
  model,
  setModel,
  run,
  busy,
  feedback,
  setError,
}: ModelFeedbackProps & {
  model: ProfileDraft | null;
  setModel: Dispatch<SetStateAction<ProfileDraft | null>>;
}) {
  const { t } = useTranslation('llm');
  const { providers, catalog, profiles } = useModelsStore();
  const runtimeEntries = catalog.filter((entry) => entry.kinds.includes(model?.value.kind as ModelInput['kind'])
    || entry.runtime_id === model?.value.runtime_id && entry.variant === model?.value.runtime_variant);
  const transformers = model?.value.runtime_variant === 'transformers-cuda';
  const audio = model?.value.runtime_variant === 'audio-cuda';
  const [remoteModels, setRemoteModels] = useState<string[]>([]);
  useEffect(() => {
    let cancelled = false;
    setRemoteModels([]);
    const id = model?.value.provider_profile_id;
    if (id)
      void modelsApi
        .listProviderModels(id)
        .then((value) => {
          if (!cancelled) setRemoteModels(value.models);
        })
        .catch((error) => {
          if (!cancelled) setError(String(error.message));
        });
    return () => {
      cancelled = true;
    };
  }, [model?.value.provider_profile_id, setError]);
  const patchModel = (patch: Partial<ModelInput>) =>
    setModel((draft) => (draft ? { ...draft, value: { ...draft.value, ...patch } } : null));
  return (
    <AppModal
      open={!!model}
      title={model?.id ? t('editModel') : t('addModel')}
      closeLabel={t('close')}
      width="large"
      onClose={() => {
        if (!busy) setModel(null);
      }}
    >
      {model ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void run(async () => {
              if (model.id) await modelsApi.patchModelProfile(model.id, model.value);
              else await modelsApi.createModelProfile(model.value);
              setModel(null);
            });
          }}
        >
          {feedback}
          <fieldset disabled={busy} className="model-form">
            <div className="model-form-grid">
              <Field label={t('name')}>
                <input required value={model.value.name} onChange={(e) => patchModel({ name: e.target.value })} />
              </Field>
              <Field label={t('alias')}>
                <input
                  required
                  pattern="[a-z0-9][a-z0-9._-]{0,127}"
                  value={model.value.alias}
                  onChange={(e) => patchModel({ alias: e.target.value })}
                />
              </Field>
              <Field label={t('kind')}>
                <select disabled value={model.value.kind}>
                  {kinds.map((k) => (
                    <option value={k} key={k}>
                      {t('kinds.' + k)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={t('backend')}>
                <select
                  value={model.value.runtime_id ? 'managed' : 'external'}
                  onChange={(e) => {
                    if (e.target.value === 'managed') {
                      const entry = runtimeEntries.find((entry) => entry.supported && entry.kinds.includes(model.value.kind));
                      if (entry) patchModel(selectManagedRuntime(model.value, entry));
                    } else patchModel({ provider_profile_id: null, runtime_id: null, runtime_variant: null, runtime_options: {} });
                  }}
                >
                  <option value="external">{model.value.kind === 'tts' ? t('unavailableBackend') : 'OpenAI Compatible'}</option>
                  <option value="managed" disabled={!runtimeEntries.some((entry) => entry.supported && entry.kinds.includes(model.value.kind))}>{t('managedBackend')}</option>
                </select>
              </Field>
              {model.value.runtime_id ? (
                <Field label={t('runtimeVariant')}>
                  <select
                    value={`${model.value.runtime_id}/${model.value.runtime_variant}`}
                    onChange={(e) => {
                      const entry = runtimeEntries.find((entry) => `${entry.runtime_id}/${entry.variant}` === e.target.value);
                      if (entry) patchModel(selectManagedRuntime(model.value, entry));
                    }}
                  >
                    {runtimeEntries.map((entry) => (
                        <option key={`${entry.runtime_id}/${entry.variant}`} value={`${entry.runtime_id}/${entry.variant}`} disabled={!entry.supported || !entry.kinds.includes(model.value.kind)}>
                          {t('runtimeFamilies.' + runtimeFamilyKey(entry.runtime_id, entry.variant))} / {runtimeBuild(entry.variant)}
                          {entry.supported && entry.kinds.includes(model.value.kind) ? '' : ` (${t(entry.reason === 'RUNTIME_NOT_IMPLEMENTED' ? 'runtimeNotImplemented' : 'runtimeStates.unsupported')})`}
                        </option>
                      ))}
                  </select>
                </Field>
              ) : model.value.kind !== 'tts' ? (
                <Field label={t('provider')}>
                  <select
                    value={model.value.provider_profile_id || ''}
                    onChange={(e) => patchModel({ provider_profile_id: e.target.value || null })}
                  >
                    <option value="">{t('unavailableBackend')}</option>
                    {providers.map((p) => (
                      <option value={p.id} key={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </Field>
              ) : null}
              <Field label={t('modelRef')}>
                <input
                  required
                  list="provider-models"
                  value={model.value.model_ref}
                  onChange={(e) => patchModel({ model_ref: e.target.value })}
                />
              </Field>
              <datalist id="provider-models">
                {remoteModels.map((id) => (
                  <option key={id} value={id} />
                ))}
              </datalist>
              <div className="model-checks">
                <Check
                  label={t('enabled')}
                  checked={model.value.enabled}
                  onChange={(enabled) => patchModel({ enabled })}
                />
                <Check
                  label={t('externalModel')}
                  checked={model.value.external_enabled}
                  onChange={(external_enabled) => patchModel({ external_enabled })}
                />
              </div>
            </div>
            {model.value.runtime_id ? (
              <>
                <h3>{t('runtimeOptions')}</h3>
                <div className="model-form-grid">
                  {(model.value.runtime_id === 'llama-server'
                    ? [
                        ['threads', 4, 1, 256],
                        ['context_size', 4096, 512, 1048576],
                        ['batch_size', 512, 1, 4096],
                        ['gpu_layers', 0, 0, model.value.runtime_variant === 'cpu' ? 0 : 999],
                      ]
                    : [['intraop_threads', 4, 1, 256]]
                  ).filter(([key]) => key !== 'gpu_layers' || model.value.runtime_variant !== 'cuda').map(([key, value, min, max]) => (
                    <NumberInput
                      key={key}
                      label={t('runtimeParams.' + key)}
                      value={Number(model.value.runtime_options[String(key)] ?? value)}
                      min={Number(min)}
                      max={Number(max)}
                      onChange={(v) =>
                        patchModel({
                          runtime_options: { ...model.value.runtime_options, [String(key)]: v ?? Number(value) },
                        })
                      }
                    />
                  ))}
                  {transformers || audio ? (
                    <Field label={t('runtimeDevice')}>
                      <select value={String(model.value.runtime_options.device ?? 'cuda')}
                        onChange={(e) => patchModel({ runtime_options: { ...model.value.runtime_options, device: e.target.value } })}>
                        <option value="cuda">NVIDIA CUDA</option>
                        <option value="cpu">CPU</option>
                      </select>
                    </Field>
                  ) : null}
                  {model.value.runtime_variant === 'cuda' ? (
                    <CudaLayersField value={typeof model.value.runtime_options.gpu_layers === 'number' ? model.value.runtime_options.gpu_layers : 'auto'}
                      onChange={(gpu_layers) => patchModel({ runtime_options: { ...model.value.runtime_options, gpu_layers } })} />
                  ) : null}
                </div>
                {transformers ? <p className="model-empty">{t('transformersDeviceHint')}</p> : null}
                {audio ? <p className="model-empty">{t('audioDeviceHint')}</p> : null}
              </>
            ) : null}
            {model.value.kind === 'llm' ? (
              <>
                <h3>{t('capabilities')}</h3>
                <div className="model-checks">
                  {(Object.keys(model.value.capabilities) as Array<keyof ModelInput['capabilities']>).map((key) => (
                    <Check
                      key={key}
                      label={t('cap.' + key)}
                      checked={model.value.capabilities[key]}
                      disabled={(model.value.runtime_id === 'llama-server' && key === 'vision') || (transformers && ['vision', 'json_object', 'json_schema'].includes(key))}
                      onChange={(v) => patchModel({ capabilities: { ...model.value.capabilities, [key]: v } })}
                    />
                  ))}
                </div>
              </>
            ) : null}
            <h3>{t('parameters')}</h3>
            <ProfileParameters value={model.value} onChange={(parameters) => patchModel({ parameters })} />
            {model.value.kind === 'tts' && model.value.parameters.architecture === 'chatterbox'
              ? <p className="model-empty">{t('chatterboxReferenceHint')}</p> : null}
            {model.value.kind === 'tts' && model.value.parameters.architecture === 'kokoro' && model.id
              && profiles.find((profile) => profile.id === model.id)?.parameters.architecture === 'kokoro'
              && profiles.find((profile) => profile.id === model.id)?.model_ref === model.value.model_ref
              ? <PresetVoices profileId={model.id} /> : null}
            <h3>{t('lifecycle')}</h3>
            <div className="model-form-grid">
              <Field label={t('release')}>
                <select
                  value={model.value.lifecycle.unload}
                  onChange={(e) =>
                    patchModel({
                      lifecycle: {
                        ...model.value.lifecycle,
                        unload: e.target.value as ModelInput['lifecycle']['unload'],
                      },
                    })
                  }
                >
                  {(['manual', 'after_request', 'idle'] as const).map((v) => (
                    <option value={v} key={v}>
                      {t('policy.' + v)}
                    </option>
                  ))}
                </select>
              </Field>
              {model.value.lifecycle.unload === 'idle' ? (
                <NumberInput
                  label={t('idleSeconds')}
                  value={model.value.lifecycle.idle_seconds}
                  min={1}
                  onChange={(v) => patchModel({ lifecycle: { ...model.value.lifecycle, idle_seconds: v ?? 300 } })}
                />
              ) : null}
            </div>
            <div className="model-form-footer">
              <button type="submit" className="primary-button">
                <Save size={16} />
                {t('save')}
              </button>
            </div>
          </fieldset>
        </form>
      ) : null}
    </AppModal>
  );
}
