import { ProfileParameters } from './ProfileParameters';
import { Save } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import { useModelsStore } from '../../../store/useModelsStore';
import type { LocalModelSource, ModelInput, ModelInventoryItem } from '../../../types/models';
import { AppModal } from '../../ui/AppModal';
import { Field, Check, NumberInput } from './fields';
import type { ModelFeedbackProps } from './types';
import { kinds, localEngine, localSource, selectModelSource, sourceValue, updateModel } from './profileDefaults';
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
  const { providers, profiles } = useModelsStore();
  const local = model?.value.source?.type === 'local' ? model.value.source : null;
  const engine = model ? localEngine(model.value) : null;
  const transformers = engine === 'transformers';
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
    const request = selectedSource === 'local'
      ? modelsApi.listModelInventory(modelKind).then((items) => {
        if (!cancelled) setInventory(items);
        return items.map((item) => item.model_ref);
      })
      : selectedSource.startsWith('provider:')
        ? modelsApi.listProviderModels(selectedSource.slice('provider:'.length)).then((value) => value.models)
        : null;
    if (request)
      void request
        .then((models) => { if (!cancelled) setRemoteModels(models); })
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
    setModel((draft) => draft?.value.source?.type === 'local'
      ? { ...draft, value: updateModel(draft.value, { source: { ...draft.value.source, ...patch } }) } : draft);
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
              <Field label={t('source')}>
                <select value={selectedSource}
                  onChange={(e) => {
                    const selected = e.target.value;
                    setModel((draft) => draft ? { ...draft, value: selectModelSource(draft.value,
                      selected === 'local' ? localSource() : selected
                        ? { type: 'provider', provider_profile_id: selected.slice('provider:'.length) } : null) } : null);
                  }}>
                  <option value="">{t('unbound')}</option>
                  {['llm', 'tts'].includes(model.value.kind) ? (
                    <optgroup label={t('localSourceGroup')}><option value="local">{t('localRuntime')}</option></optgroup>
                  ) : null}
                  {['llm', 'embedding'].includes(model.value.kind) && providers.length ? (
                    <optgroup label={t('providers')}>
                      {providers.map((provider) => (
                        <option value={`provider:${provider.id}`} key={provider.id}>
                          {provider.name}{provider.enabled ? '' : ` (${t('disabled')})`}
                        </option>
                      ))}
                    </optgroup>
                  ) : null}
                </select>
              </Field>
              <Field label={t('modelRef')}>
                <input
                  required
                  list="source-models"
                  value={model.value.model_ref}
                  onChange={(e) => patchModel({ model_ref: e.target.value })}
                />
              </Field>
              <datalist id="source-models">
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
            {model.value.source?.type === 'provider' ? <p className="model-empty">{t('providerModelHint')}</p> : null}
            {discoveryError ? <p role="status" className="model-empty">{t('discoveryUnavailable')} {discoveryError}</p> : null}
            {engine && local ? (
              <>
                <h3>{t('executionOptions')}</h3>
                <p className="model-empty">{t('engine')}: {t('engines.' + engine)}</p>
                <div className="model-form-grid">
                  <Field label={t('runtimeDevice')}>
                    <select value={String(local.execution_options.device)} disabled={engine === 'kokoro'}
                      onChange={(e) => patchLocal({ execution_options: {
                        ...local.execution_options, device: e.target.value,
                        ...(engine === 'llama-server' ? { gpu_layers: e.target.value === 'cpu' ? 0 : 'auto' } : {}),
                      } })}>
                      <option value="cuda">NVIDIA CUDA</option><option value="cpu">CPU</option>
                    </select>
                  </Field>
                  {(engine === 'llama-server'
                    ? [['threads', 4, 1, 256], ['context_size', 4096, 512, 1048576], ['batch_size', 512, 1, 4096]]
                    : [['intraop_threads', 4, 1, 256]]).map(([key, initial, min, max]) => (
                    <NumberInput key={String(key)} label={t('runtimeParams.' + key)}
                      value={Number(local.execution_options[String(key)] ?? initial)} min={Number(min)} max={Number(max)}
                      onChange={(value) => patchLocal({ execution_options: { ...local.execution_options, [String(key)]: value ?? Number(initial) } })} />
                  ))}
                  {engine === 'llama-server' && local.execution_options.device === 'cuda' ? (
                    <CudaLayersField value={typeof local.execution_options.gpu_layers === 'number' ? local.execution_options.gpu_layers : 'auto'}
                      onChange={(gpu_layers) => patchLocal({ execution_options: { ...local.execution_options, gpu_layers } })} />
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
                      disabled={transformers && ['json_object', 'json_schema'].includes(key)}
                      onChange={(v) => patchModel({ capabilities: { ...model.value.capabilities, [key]: v } })}
                    />
                  ))}
                </div>
                {engine === 'llama-server' && local && model.value.capabilities.vision ? <>
                  <Field label={t('mmprojRef')}>
                    <input required list="model-projectors" value={String(local.execution_options.mmproj_ref ?? '')}
                      onChange={(event) => patchLocal({ execution_options: { ...local.execution_options, mmproj_ref: event.target.value || null } })} />
                  </Field>
                  <datalist id="model-projectors">
                    {(inventory.find((item) => item.model_ref === model.value.model_ref)?.mmproj_refs ?? []).map((ref) => <option key={ref} value={ref} />)}
                  </datalist>
                  <p className="model-empty">{t('mmprojHint')}</p>
                </> : null}
              </>
            ) : null}
            <h3>{t('parameters')}</h3>
            <ProfileParameters value={model.value} onChange={(parameters) => patchModel({ parameters })} />
            {audio ? <p className="model-empty">{t('ttsSeedHint')}</p> : null}
            {model.value.kind === 'tts' && model.value.parameters.architecture === 'chatterbox'
              ? <p className="model-empty">{t('chatterboxReferenceHint')}</p> : null}
            {model.value.kind === 'tts' && model.value.parameters.architecture === 'qwen3tts'
              ? <p className="model-empty">{t('qwenReferenceHint')}</p> : null}
            {local && model.value.kind === 'tts' && model.value.parameters.architecture === 'kokoro' && model.id
              && profiles.find((profile) => profile.id === model.id)?.parameters.architecture === 'kokoro'
              && profiles.find((profile) => profile.id === model.id)?.model_ref === model.value.model_ref
              ? <PresetVoices profileId={model.id} /> : null}
            {local ? <>
            <h3>{t('lifecycle')}</h3>
            <div className="model-form-grid">
              <Field label={t('release')}>
                <select
                  value={local.lifecycle.unload}
                  onChange={(e) =>
                    patchLocal({
                      lifecycle: {
                        ...local.lifecycle,
                        unload: e.target.value as LocalModelSource['lifecycle']['unload'],
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
              {local.lifecycle.unload === 'idle' ? (
                <NumberInput
                  label={t('idleSeconds')}
                  value={local.lifecycle.idle_seconds}
                  min={1}
                  onChange={(v) => patchLocal({ lifecycle: { ...local.lifecycle, idle_seconds: v ?? 300 } })}
                />
              ) : null}
            </div>
            </> : null}
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
