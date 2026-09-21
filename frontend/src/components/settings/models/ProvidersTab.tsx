import { Pencil, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import { useModelsStore } from '../../../store/useModelsStore';
import { Icon } from './fields';
import type { ModelFeedbackProps } from './types';
import { newProvider } from './profileDefaults';
import { ProviderEditor, type ProviderDraft } from './ProviderEditor';

export function ProvidersTab({ run, busy, feedback, setError }: ModelFeedbackProps) {
  const { t } = useTranslation('llm');
  const { providers } = useModelsStore();
  const [provider, setProvider] = useState<ProviderDraft | null>(null);
  return (
    <>
      <div className="model-toolbar">
        <h3>{t('providers')}</h3>
        <button className="secondary-button" disabled={busy} onClick={() => {
          setError(''); setProvider({ value: newProvider() });
        }}><Plus size={16} />{t('addProvider')}</button>
      </div>
      <p>{t('providerSummary')}</p>
      {providers.map((item) => (
        <div className="model-row" key={item.id}>
          <div className="model-identity">
            <strong>{item.name}</strong>
            <small>{item.connection.base_url}</small>
            <small>{item.enabled ? t('enabled') : t('disabled')}</small>
          </div>
          <div className="model-actions">
            <Icon label={t('edit')} disabled={busy} onClick={() => {
              const { has_api_key: _key, ...connection } = item.connection;
              setError('');
              setProvider({ id: item.id, value: { name: item.name, enabled: item.enabled, connection } });
            }}><Pencil size={16} /></Icon>
            <Icon label={t('delete')} disabled={busy} onClick={() => void run(() => modelsApi.deleteProviderProfile(item.id))}>
              <Trash2 size={16} />
            </Icon>
          </div>
        </div>
      ))}
      {!providers.length ? <p className="model-empty">{t('emptyProviders')}</p> : null}
      <ProviderEditor provider={provider} setProvider={setProvider} run={run} busy={busy} feedback={feedback} setError={setError} />
    </>
  );
}
