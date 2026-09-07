import { Pencil, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';

import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import { useModelsStore } from '../../../store/useModelsStore';

import { Icon } from './fields';
import type { ModelFeedbackProps } from './types';
import { newProvider } from './profileDefaults';
import { ConnectionEditor, type ConnectionDraft } from './ConnectionEditor';

export function ConnectionsTab({ run, busy, feedback, setError }: ModelFeedbackProps) {
  const { t } = useTranslation('llm');
  const { providers, loading } = useModelsStore();
  const [provider, setProvider] = useState<ConnectionDraft | null>(null);
  return (
    <>
      <>
        <div className="model-toolbar">
          <span>OpenAI Compatible</span>
          <button
            className="secondary-button"
            disabled={busy}
            onClick={() => {
              setError('');
              setProvider({ value: newProvider() });
            }}
          >
            <Plus size={16} />
            {t('addProvider')}
          </button>
        </div>
        {providers.map((p) => (
          <div className="model-row" key={p.id}>
            <div className="model-identity">
              <strong>{p.name}</strong>
              <small>{p.base_url}</small>
              <small>{p.enabled ? t('enabled') : t('disabled')}</small>
            </div>
            <div className="model-actions">
              <Icon
                label={t('edit')}
                disabled={busy}
                onClick={() => {
                  const { id, created_at: _c, updated_at: _u, has_api_key: _k, ...value } = p;
                  setError('');
                  setProvider({ id, value });
                }}
              >
                <Pencil size={16} />
              </Icon>
              <Icon
                label={t('delete')}
                disabled={busy}
                onClick={() => void run(() => modelsApi.deleteProviderProfile(p.id))}
              >
                <Trash2 size={16} />
              </Icon>
            </div>
          </div>
        ))}
        {!providers.length && !loading ? <p className="model-empty">{t('emptyProviders')}</p> : null}
      </>
      <ConnectionEditor
        provider={provider}
        setProvider={setProvider}
        run={run}
        busy={busy}
        feedback={feedback}
        setError={setError}
      />
    </>
  );
}
