import { Card, CardHeader, CardTitle, CardDescription, CardAction } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { ResourceEmpty } from '../resources/ResourceUI';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import { useModelsStore } from '../../../store/useModelsStore';

import type { ModelFeedbackProps } from './types';
import { newProvider } from './profileDefaults';
import { ProviderEditor, type ProviderDraft } from './ProviderEditor';

export function ProvidersTab({ run, busy, feedback, setError }: ModelFeedbackProps) {
  const { t } = useTranslation('llm');
  const { providers, loading, reload } = useModelsStore();
  const [provider, setProvider] = useState<ProviderDraft | null>(null);
  const disabled = busy || loading;
  return (
    <>
      <div className="model-toolbar">
        <h3>{t('providers')}</h3>
        <div className="model-actions">
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={t('refresh')}
                  disabled={disabled}
                  onClick={() => void run(reload, false)}
                />
              }
            >
              <RefreshCw data-icon="inline-start" />
            </TooltipTrigger>
            <TooltipContent>{t('refresh')}</TooltipContent>
          </Tooltip>
          <Button
            disabled={disabled}
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
      </div>
      {providers.length ? (
        <div className="grid min-w-0 grid-cols-1 gap-4">
          {providers.map((item) => (
            <Card className="provider-card min-w-0" role="group" aria-label={item.name} key={item.id}>
              <CardHeader className="flex min-h-11 flex-wrap items-center gap-4">
                <Switch
                  checked={item.enabled}
                  aria-label={t('providerEnabled', { name: item.name })}
                  disabled={disabled}
                  onCheckedChange={(enabled) => void run(() => modelsApi.patchProviderProfile(item.id, { enabled }))}
                />
                <div className="flex min-w-0 flex-1 flex-col gap-1 [overflow-wrap:anywhere]">
                  <CardTitle>{item.name}</CardTitle>
                  <CardDescription>{item.connection.base_url}</CardDescription>
                </div>
                <CardAction className="flex items-center gap-2 self-center max-md:basis-full max-md:justify-end">
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          aria-label={t('edit')}
                          disabled={disabled}
                          onClick={() => {
                            const { has_api_key: _key, ...connection } = item.connection;
                            setError('');
                            setProvider({ id: item.id, value: { name: item.name, connection } });
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
                          disabled={disabled}
                          onClick={() => void run(() => modelsApi.deleteProviderProfile(item.id))}
                        />
                      }
                    >
                      <Trash2 data-icon="inline-start" />
                    </TooltipTrigger>
                    <TooltipContent>{t('delete')}</TooltipContent>
                  </Tooltip>
                </CardAction>
              </CardHeader>
            </Card>
          ))}
        </div>
      ) : <ResourceEmpty>{t('emptyProviders')}</ResourceEmpty>}
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
