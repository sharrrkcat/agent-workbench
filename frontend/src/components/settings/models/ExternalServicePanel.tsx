import { Copy, KeyRound, Save } from 'lucide-react';
import { useState } from 'react';

import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import { useModelsStore } from '../../../store/useModelsStore';

import { Field, Check, Icon, NumberInput } from './fields';
import type { ModelFeedbackProps } from './types';

export function ExternalServicePanel({ run, busy }: Pick<ModelFeedbackProps, 'run' | 'busy'>) {
  const { t } = useTranslation('llm');
  const settings = useModelsStore((state) => state.settings);
  const [apiKey, setApiKey] = useState('');
  if (!settings) return null;
  return (
    <div className="model-service">
      <Check
        label={t('externalEnabled')}
        checked={settings.external_enabled}
        disabled={busy}
        onChange={(external_enabled) => void run(() => modelsApi.updateModelSettings({ external_enabled }))}
      />
      <Field label={t('apiKey')}>
        <div className="model-actions">
          <input
            aria-label={t('apiKey')}
            type="password"
            autoComplete="new-password"
            placeholder={settings.has_external_api_key ? t('keySet') : ''}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
          />
          <Icon label={t('generateKey')} onClick={() => setApiKey(crypto.randomUUID() + crypto.randomUUID())}>
            <KeyRound size={16} />
          </Icon>
          <Icon
            label={t('copy')}
            disabled={!apiKey}
            onClick={() => void run(() => navigator.clipboard.writeText(apiKey), false)}
          >
            <Copy size={16} />
          </Icon>
          <Icon
            label={t('save')}
            disabled={!apiKey || busy}
            onClick={() =>
              void run(async () => {
                await modelsApi.updateModelSettings({ external_api_key: apiKey });
                setApiKey('');
              })
            }
          >
            <Save size={16} />
          </Icon>
        </div>
      </Field>
      <NumberInput
        label={t('bodyLimit')}
        value={settings.max_request_mb}
        min={1}
        max={100}
        onChange={(v) => {
          if (v != null) void run(() => modelsApi.updateModelSettings({ max_request_mb: v }));
        }}
      />
    </div>
  );
}
