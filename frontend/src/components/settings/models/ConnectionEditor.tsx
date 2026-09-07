import { Save } from 'lucide-react';

import type { Dispatch, SetStateAction } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import { useModelsStore } from '../../../store/useModelsStore';
import type { ProviderInput } from '../../../types/models';
import { AppModal } from '../../ui/AppModal';
import { Field, Check, NumberInput } from './fields';
import type { ModelFeedbackProps } from './types';

export type ConnectionDraft = { id?: string; value: ProviderInput };
export function ConnectionEditor({
  provider,
  setProvider,
  run,
  busy,
  feedback,
}: ModelFeedbackProps & {
  provider: ConnectionDraft | null;
  setProvider: Dispatch<SetStateAction<ConnectionDraft | null>>;
}) {
  const { t } = useTranslation('llm');
  const providers = useModelsStore((state) => state.providers);
  const patchProvider = (patch: Partial<ProviderInput>) =>
    setProvider((draft) => (draft ? { ...draft, value: { ...draft.value, ...patch } } : null));
  return (
    <AppModal
      open={!!provider}
      title={provider?.id ? t('editProvider') : t('addProvider')}
      closeLabel={t('close')}
      onClose={() => {
        if (!busy) setProvider(null);
      }}
    >
      {provider ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void run(async () => {
              if (provider.id) await modelsApi.patchProviderProfile(provider.id, provider.value);
              else await modelsApi.createProviderProfile(provider.value);
              setProvider(null);
            });
          }}
        >
          {feedback}
          <fieldset disabled={busy} className="model-form">
            <Field label={t('name')}>
              <input required value={provider.value.name} onChange={(e) => patchProvider({ name: e.target.value })} />
            </Field>
            <Field label={t('baseUrl')}>
              <input
                required
                type="url"
                value={provider.value.base_url}
                onChange={(e) => patchProvider({ base_url: e.target.value })}
              />
            </Field>
            <Field label={t('apiKey')}>
              <input
                type="password"
                autoComplete="new-password"
                value={provider.value.api_key ?? ''}
                placeholder={providers.find((p) => p.id === provider.id)?.has_api_key ? t('keySet') : ''}
                onChange={(e) => patchProvider({ api_key: e.target.value })}
              />
            </Field>
            <div className="model-form-grid">
              {(['timeout_seconds', 'concurrency', 'queue_size', 'queue_timeout_seconds'] as const).map((key) => (
                <NumberInput
                  key={key}
                  label={t('connection.' + key)}
                  value={provider.value[key]}
                  min={key === 'queue_size' ? 0 : 1}
                  onChange={(v) => patchProvider({ [key]: v ?? 1 })}
                />
              ))}
            </div>
            <Check
              label={t('enabled')}
              checked={provider.value.enabled}
              onChange={(enabled) => patchProvider({ enabled })}
            />
            <div className="model-form-footer">
              <button className="primary-button" type="submit">
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
