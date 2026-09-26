import { Switch } from '@/components/ui/switch';
import { Field, FieldLabel, FieldGroup, FieldDescription } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { InputGroup, InputGroupInput, InputGroupAddon, InputGroupButton } from '@/components/ui/input-group';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Copy, KeyRound, Save } from 'lucide-react';
import { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import { useModelsStore } from '../../../store/useModelsStore';

import type { ModelFeedbackProps } from './types';

function RequestLimitField({ label, description, value, max, busy, onSave }: {
  label: string;
  description: string;
  value: number;
  max: number;
  busy: boolean;
  onSave: (value: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);
  const number = Number(draft);
  const invalid = draft === '' || !Number.isInteger(number) || number < 1 || number > max;
  return (
    <Field disabled={busy} data-invalid={invalid || undefined}>
      <FieldLabel>{label}</FieldLabel>
      <Input
        type="number"
        required
        min={1}
        max={max}
        step={1}
        disabled={busy}
        aria-invalid={invalid}
        value={draft}
        onChange={(event) => setDraft(event.currentTarget.value)}
        onBlur={(event) => {
          if (!busy && !invalid && event.currentTarget.validity.valid && number !== value) onSave(number);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            if (event.currentTarget.reportValidity()) event.currentTarget.blur();
          }
        }}
      />
      <FieldDescription>{description}</FieldDescription>
    </Field>
  );
}

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
      <RequestLimitField
        label={t('bodyLimit')}
        description={t('bodyLimitHelp')}
        value={settings.max_request_mb}
        max={100}
        busy={busy}
        onSave={(max_request_mb) => void run(() => modelsApi.updateModelSettings({ max_request_mb }))}
      />
      <RequestLimitField
        label={t('normalizedBodyLimit')}
        description={t('normalizedBodyLimitHelp')}
        value={settings.max_normalized_request_mb}
        max={1024}
        busy={busy}
        onSave={(max_normalized_request_mb) =>
          void run(() => modelsApi.updateModelSettings({ max_normalized_request_mb }))
        }
      />
    </FieldGroup>
  );
}
