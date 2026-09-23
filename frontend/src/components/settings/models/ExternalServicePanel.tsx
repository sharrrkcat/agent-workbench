import { Switch } from '@/components/ui/switch';
import { Field, FieldLabel, FieldGroup } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { InputGroup, InputGroupInput, InputGroupAddon, InputGroupButton } from '@/components/ui/input-group';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Copy, KeyRound, Save } from 'lucide-react';
import { useState } from 'react';

import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import { useModelsStore } from '../../../store/useModelsStore';

import type { ModelFeedbackProps } from './types';

export function ExternalServicePanel({ run, busy }: Pick<ModelFeedbackProps, 'run' | 'busy'>) {
  const { t } = useTranslation('llm');
  const settings = useModelsStore((state) => state.settings);
  const [apiKey, setApiKey] = useState('');
  if (!settings) return null;
  return (
    <FieldGroup className="model-service">
      <Field orientation="horizontal" disabled={busy}>
        <Switch
          checked={settings.external_enabled}
          disabled={busy}
          onCheckedChange={(external_enabled) =>
            void run(() => modelsApi.updateModelSettings({ external_enabled }))
          }
        />
        <FieldLabel>{t('externalEnabled')}</FieldLabel>
      </Field>
      <Field>
        <FieldLabel>{t('apiKey')}</FieldLabel>
        <InputGroup>
          <InputGroupInput
            aria-label={t('apiKey')}
            type="password"
            autoComplete="new-password"
            placeholder={settings.has_external_api_key ? t('keySet') : ''}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
          <InputGroupAddon align="inline-end">
            <Tooltip>
              <TooltipTrigger
                render={
                  <InputGroupButton
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={t('generateKey')}
                    onClick={() => setApiKey(crypto.randomUUID() + crypto.randomUUID())}
                  />
                }
              >
                <KeyRound data-icon="inline-start" />
              </TooltipTrigger>
              <TooltipContent>{t('generateKey')}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger
                render={
                  <InputGroupButton
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={t('copy')}
                    disabled={!apiKey}
                    onClick={() => void run(() => navigator.clipboard.writeText(apiKey), false)}
                  />
                }
              >
                <Copy data-icon="inline-start" />
              </TooltipTrigger>
              <TooltipContent>{t('copy')}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger
                render={
                  <InputGroupButton
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label={t('save')}
                    disabled={!apiKey || busy}
                    onClick={() =>
                      void run(async () => {
                        await modelsApi.updateModelSettings({ external_api_key: apiKey });
                        setApiKey('');
                      })
                    }
                  />
                }
              >
                <Save data-icon="inline-start" />
              </TooltipTrigger>
              <TooltipContent>{t('save')}</TooltipContent>
            </Tooltip>
          </InputGroupAddon>
        </InputGroup>
      </Field>
      <Field>
        <FieldLabel>{t('bodyLimit')}</FieldLabel>
        <Input
          type="number"
          min={1}
          max={100}
          step={1}
          value={Number.isNaN(settings.max_request_mb) ? '' : (settings.max_request_mb ?? '')}
          onChange={(event) => {
            const raw = event.currentTarget.value;
            if (raw !== '') void run(() => modelsApi.updateModelSettings({ max_request_mb: Number(raw) }));
          }}
        />
      </Field>
    </FieldGroup>
  );
}
