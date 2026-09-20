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
import { kinds, localEngine, updateModel } from './profileDefaults';
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
  const { backends, profiles } = useModelsStore();
  const engine = model ? localEngine(model.value) : null;
  const transformers = engine === 'transformers';
  const audio = engine === 'chatterbox' || engine === 'qwen3tts';
  const [remoteModels, setRemoteModels] = useState<string[]>([]);
  useEffect(() => {
    let cancelled = false;
    setRemoteModels([]);
    const id = model?.value.backend_profile_id;
    if (id && id !== 'local')
      void modelsApi
        .listBackendModels(id)
        .then((value) => {
          if (!cancelled) setRemoteModels(value.models);
        })
        .catch((error) => {
          if (!cancelled) setError(String(error.message));
        });
    return () => {
      cancelled = true;
    };
  }, [model?.value.backend_profile_id, setError]);
  const patchModel = (patch: Partial<ModelInput>) =>
    setModel((draft) => (draft ? { ...draft, value: updateModel(draft.value, patch) } : null));
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
                <select value={model.value.backend_profile_id || ''}
                  onChange={(e) => patchModel({ backend_profile_id: e.target.value || null })}>
                  <option value="">{t('unavailableBackend')}</option>
                  {backends.filter((backend) => backend.type === 'local'
                    ? ['llm', 'tts'].includes(model.value.kind) : model.value.kind !== 'tts').map((backend) => (
                    <option value={backend.id} key={backend.id}>
                      {backend.type === 'local' ? t('localBackend') : backend.name}{backend.enabled ? '' : ` (${t('disabled')})`}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={t('modelRef')}>
                <input
                  required
                  list="backend-models"
                  value={model.value.model_ref}
                  onChange={(e) => patchModel({ model_ref: e.target.value })}
                />
              </Field>
              <datalist id="backend-models">
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
            {engine ? (
              <>
                <h3>{t('executionOptions')}</h3>
                <p className="model-empty">{t('engine')}: {t('engines.' + engine)}</p>
                <div className="model-form-grid">
                  <Field label={t('runtimeDevice')}>
                    <select value={String(model.value.execution_options.device)} disabled={engine === 'kokoro'}
                      onChange={(e) => patchModel({ execution_options: {
                        ...model.value.execution_options, device: e.target.value,
                        ...(engine === 'llama-server' ? { gpu_layers: e.target.value === 'cpu' ? 0 : 'auto' } : {}),
                      } })}>
                      <option value="cuda">NVIDIA CUDA</option><option value="cpu">CPU</option>
                    </select>
                  </Field>
                  {(engine === 'llama-server'
                    ? [['threads', 4, 1, 256], ['context_size', 4096, 512, 1048576], ['batch_size', 512, 1, 4096]]
                    : [['intraop_threads', 4, 1, 256]]).map(([key, initial, min, max]) => (
                    <NumberInput key={String(key)} label={t('runtimeParams.' + key)}
                      value={Number(model.value.execution_options[String(key)] ?? initial)} min={Number(min)} max={Number(max)}
                      onChange={(value) => patchModel({ execution_options: { ...model.value.execution_options, [String(key)]: value ?? Number(initial) } })} />
                  ))}
                  {engine === 'llama-server' && model.value.execution_options.device === 'cuda' ? (
                    <CudaLayersField value={typeof model.value.execution_options.gpu_layers === 'number' ? model.value.execution_options.gpu_layers : 'auto'}
                      onChange={(gpu_layers) => patchModel({ execution_options: { ...model.value.execution_options, gpu_layers } })} />
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
                      disabled={(engine === 'llama-server' && key === 'vision') || (transformers && ['vision', 'json_object', 'json_schema'].includes(key))}
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
            {model.value.kind === 'tts' && model.value.parameters.architecture === 'qwen3tts'
              ? <p className="model-empty">{t('qwenReferenceHint')}</p> : null}
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
