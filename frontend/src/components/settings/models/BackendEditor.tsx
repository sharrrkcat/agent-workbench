import { Save } from 'lucide-react';

import type { Dispatch, SetStateAction } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import { useModelsStore } from '../../../store/useModelsStore';
import type { ExternalBackendInput, ExternalConnection } from '../../../types/models';
import { AppModal } from '../../ui/AppModal';
import { Field, Check, NumberInput } from './fields';
import type { ModelFeedbackProps } from './types';

export type BackendDraft = { id?: string; value: ExternalBackendInput };
export function BackendEditor({
  backend,
  setBackend,
  run,
  busy,
  feedback,
}: ModelFeedbackProps & {
  backend: BackendDraft | null;
  setBackend: Dispatch<SetStateAction<BackendDraft | null>>;
}) {
  const { t } = useTranslation('llm');
  const backends = useModelsStore((state) => state.backends);
  const patchBackend = (patch: Partial<ExternalBackendInput>) =>
    setBackend((draft) => (draft ? { ...draft, value: { ...draft.value, ...patch } } : null));
  const patchConnection = (patch: Partial<ExternalConnection>) =>
    setBackend((draft) => draft ? { ...draft, value: { ...draft.value, connection: { ...draft.value.connection, ...patch } } } : null);
  return (
    <AppModal
      open={!!backend}
      title={backend?.id ? t('editBackend') : t('addBackend')}
      closeLabel={t('close')}
      onClose={() => {
        if (!busy) setBackend(null);
      }}
    >
      {backend ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void run(async () => {
              if (backend.id) await modelsApi.patchBackendProfile(backend.id, backend.value);
              else await modelsApi.createBackendProfile(backend.value);
              setBackend(null);
            });
          }}
        >
          {feedback}
          <fieldset disabled={busy} className="model-form">
            <Field label={t('name')}>
              <input required value={backend.value.name} onChange={(e) => patchBackend({ name: e.target.value })} />
            </Field>
            <Field label={t('baseUrl')}>
              <input
                required
                type="url"
                value={backend.value.connection.base_url}
                onChange={(e) => patchConnection({ base_url: e.target.value })}
              />
            </Field>
            <Field label={t('apiKey')}>
              <input
                type="password"
                autoComplete="new-password"
                value={backend.value.connection.api_key ?? ''}
                placeholder={backends.find((p) => p.id === backend.id)?.connection?.has_api_key ? t('keySet') : ''}
                onChange={(e) => patchConnection({ api_key: e.target.value })}
              />
            </Field>
            <div className="model-form-grid">
              {(['timeout_seconds', 'concurrency', 'queue_size', 'queue_timeout_seconds'] as const).map((key) => (
                <NumberInput
                  key={key}
                  label={t('connection.' + key)}
                  value={backend.value.connection[key]}
                  min={key === 'queue_size' ? 0 : 1}
                  onChange={(v) => patchConnection({ [key]: v ?? 1 })}
                />
              ))}
            </div>
            <Check
              label={t('enabled')}
              checked={backend.value.enabled}
              onChange={(enabled) => patchBackend({ enabled })}
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
