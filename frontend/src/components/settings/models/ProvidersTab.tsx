import { Badge } from '@/components/ui/badge';
import { ResourceEmpty } from '../resources/ResourceUI';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Pencil, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import { useModelsStore } from '../../../store/useModelsStore';

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
        <Button
          disabled={busy}
          onClick={() => {
            setError('');
            setProvider({ value: newProvider() });
          }}
          type="button"
          variant="outline"
        >
          <Plus data-icon="inline-start" />
          {t('addProvider')}
        </Button>
      </div>
      <p>{t('providerSummary')}</p>
      {providers.map((item) => (
        <div className="model-row" key={item.id}>
          <div className="model-identity">
            <strong>{item.name}</strong>
            <small>{item.connection.base_url}</small>
            <Badge variant={item.enabled ? 'secondary' : 'outline'}>
              {item.enabled ? t('enabled') : t('disabled')}
            </Badge>
          </div>
          <div className="model-actions">
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label={t('edit')}
                    disabled={busy}
                    onClick={() => {
                      const { has_api_key: _key, ...connection } = item.connection;
                      setError('');
                      setProvider({
                        id: item.id,
                        value: { name: item.name, enabled: item.enabled, connection },
                      });
                    }}
                  />
                }
              >
                <Pencil data-icon="inline-start" />
              </TooltipTrigger>
              <TooltipContent>{t('edit')}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label={t('delete')}
                    disabled={busy}
                    onClick={() => void run(() => modelsApi.deleteProviderProfile(item.id))}
                  />
                }
              >
                <Trash2 data-icon="inline-start" />
              </TooltipTrigger>
              <TooltipContent>{t('delete')}</TooltipContent>
            </Tooltip>
          </div>
        </div>
      ))}
      {!providers.length ? <ResourceEmpty>{t('emptyProviders')}</ResourceEmpty> : null}
      <ProviderEditor
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
