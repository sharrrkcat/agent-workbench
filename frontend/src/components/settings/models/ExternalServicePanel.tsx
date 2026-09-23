import { Switch } from '@/components/ui/switch';
import { Field, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
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
    <div className="model-service">
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
        <div className="model-actions">
          <Input
            aria-label={t('apiKey')}
            type="password"
            autoComplete="new-password"
            placeholder={settings.has_external_api_key ? t('keySet') : ''}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={t('generateKey')}
                  onClick={() => setApiKey(crypto.randomUUID() + crypto.randomUUID())}
                />
              }
            >
              <KeyRound size={16} />
            </TooltipTrigger>
            <TooltipContent>{t('generateKey')}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={t('copy')}
                  disabled={!apiKey}
                  onClick={() => void run(() => navigator.clipboard.writeText(apiKey), false)}
                />
              }
            >
              <Copy size={16} />
            </TooltipTrigger>
            <TooltipContent>{t('copy')}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
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
              <Save size={16} />
            </TooltipTrigger>
            <TooltipContent>{t('save')}</TooltipContent>
          </Tooltip>
        </div>
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
    </div>
  );
}
