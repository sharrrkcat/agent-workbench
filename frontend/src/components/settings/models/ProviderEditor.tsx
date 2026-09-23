import { useSettingsView } from '../SettingsView';
import { Input } from '@/components/ui/input';
import { FieldGroup, Field, FieldLabel, FieldSet } from '@/components/ui/field';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Save } from 'lucide-react';

import type { Dispatch, SetStateAction } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import { useModelsStore } from '../../../store/useModelsStore';
import type { ProviderInput, ExternalConnection } from '../../../types/models';

import type { ModelFeedbackProps } from './types';

export type ProviderDraft = { id?: string; value: ProviderInput };
export function ProviderEditor({
  provider,
  setProvider,
  run,
  busy,
  feedback,
}: ModelFeedbackProps & {
  provider: ProviderDraft | null;
  setProvider: Dispatch<SetStateAction<ProviderDraft | null>>;
}) {
  const { t } = useTranslation('llm');
  const activeView = useSettingsView();
  const providers = useModelsStore((state) => state.providers);
  const patchProvider = (patch: Partial<ProviderInput>) =>
    setProvider((draft) => (draft ? { ...draft, value: { ...draft.value, ...patch } } : null));
  const patchConnection = (patch: Partial<ExternalConnection>) =>
    setProvider((draft) =>
      draft
        ? { ...draft, value: { ...draft.value, connection: { ...draft.value.connection, ...patch } } }
        : null,
    );
  return (
    <Dialog
      open={activeView && !!provider}
      onOpenChange={(open) => {
        if (!open)
          (() => {
            if (!busy) setProvider(null);
          })();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{provider?.id ? t('editProvider') : t('addProvider')}</DialogTitle>
        </DialogHeader>
        {provider ? (
          <form
            className="settings-dialog-form"
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                if (provider.id) await modelsApi.patchProviderProfile(provider.id, provider.value);
                else await modelsApi.createProviderProfile(provider.value);
                setProvider(null);
              });
            }}
          >
            <div className="settings-dialog-body">
              {feedback}
              <FieldSet disabled={busy} className="model-form">
                <Field>
                  <FieldLabel>{t('name')}</FieldLabel>
                  <Input
                    required
                    value={provider.value.name}
                    onChange={(e) => patchProvider({ name: e.target.value })}
                  />
                </Field>
                <Field>
                  <FieldLabel>{t('baseUrl')}</FieldLabel>
                  <Input
                    required
                    type="url"
                    value={provider.value.connection.base_url}
                    onChange={(e) => patchConnection({ base_url: e.target.value })}
                  />
                </Field>
                <Field>
                  <FieldLabel>{t('apiKey')}</FieldLabel>
                  <Input
                    type="password"
                    autoComplete="new-password"
                    value={provider.value.connection.api_key ?? ''}
                    placeholder={
                      providers.find((p) => p.id === provider.id)?.connection?.has_api_key ? t('keySet') : ''
                    }
                    onChange={(e) => patchConnection({ api_key: e.target.value })}
                  />
                </Field>
                <FieldGroup className="grid gap-4 sm:grid-cols-2">
                  {(['timeout_seconds', 'concurrency', 'queue_size', 'queue_timeout_seconds'] as const).map(
                    (key) => (
                      <Field key={key}>
                        <FieldLabel>{t('connection.' + key)}</FieldLabel>
                        <Input
                          type="number"
                          min={key === 'queue_size' ? 0 : 1}
                          step={1}
                          value={
                            Number.isNaN(provider.value.connection[key])
                              ? ''
                              : (provider.value.connection[key] ?? '')
                          }
                          onChange={(event) =>
                            patchConnection({
                              [key]: event.currentTarget.value === '' ? 1 : Number(event.currentTarget.value),
                            })
                          }
                        />
                      </Field>
                    ),
                  )}
                </FieldGroup>
                <Field orientation="horizontal">
                  <Switch
                    checked={provider.value.enabled}
                    onCheckedChange={(enabled) => patchProvider({ enabled })}
                  />
                  <FieldLabel>{t('enabled')}</FieldLabel>
                </Field>
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
