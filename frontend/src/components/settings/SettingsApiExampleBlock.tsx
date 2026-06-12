import { Check, Clipboard } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

export type SettingsApiExample = {
  id: string;
  title: string;
  body: string;
  description?: string;
};

export function formatApiExampleJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export function SettingsApiExampleBlock({
  endpoint,
  method = 'POST',
  modelId,
  modelIdHelp,
  examples,
  note,
}: {
  endpoint: string;
  method?: string;
  modelId: string;
  modelIdHelp?: string;
  examples: SettingsApiExample[];
  note?: string;
}) {
  const { t } = useTranslation('settings');
  const [copiedTarget, setCopiedTarget] = useState('');
  const [copyError, setCopyError] = useState('');

  useEffect(() => {
    if (!copiedTarget) return undefined;
    const timeout = window.setTimeout(() => setCopiedTarget(''), 1800);
    return () => window.clearTimeout(timeout);
  }, [copiedTarget]);

  async function copyText(target: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopyError('');
      setCopiedTarget(target);
    } catch {
      setCopiedTarget('');
      setCopyError(t('apiExamples.copyFailed'));
    }
  }

  function requestSnippet(body: string): string {
    return `${method} ${endpoint}\nContent-Type: application/json\n\n${body}`;
  }

  return (
    <section className="detail-section">
      <div className="detail-section-heading">
        <h3>{t('apiExamples.title')}</h3>
        <span className="settings-badge muted">{method} {endpoint}</span>
      </div>
      <p className="settings-muted-copy">{t('apiExamples.help')}</p>
      <div className="knowledge-command-card">
        <div className="knowledge-command-card-body">
          <strong>{t('apiExamples.modelId')}</strong>
          <code>{modelId}</code>
          {modelIdHelp ? <span className="settings-muted-text">{modelIdHelp}</span> : null}
        </div>
        <button className="settings-secondary-button" type="button" onClick={() => void copyText('model-id', modelId)} aria-label={t('apiExamples.copyModelId')}>
          {copiedTarget === 'model-id' ? <Check size={14} /> : <Clipboard size={14} />}
          {copiedTarget === 'model-id' ? t('apiExamples.copied') : t('apiExamples.copyModelId')}
        </button>
      </div>
      {note ? <p className="settings-muted-copy">{note}</p> : null}
      {examples.length ? examples.map((example) => (
        <div className="knowledge-command-card" key={example.id}>
          <div className="knowledge-command-card-body">
            <strong>{example.title}</strong>
            {example.description ? <span className="settings-muted-text">{example.description}</span> : null}
            <code>{example.body}</code>
          </div>
          <button className="settings-secondary-button" type="button" onClick={() => void copyText(`example:${example.id}`, requestSnippet(example.body))} aria-label={t('apiExamples.copyExample')}>
            {copiedTarget === `example:${example.id}` ? <Check size={14} /> : <Clipboard size={14} />}
            {copiedTarget === `example:${example.id}` ? t('apiExamples.copied') : t('apiExamples.copyExample')}
          </button>
        </div>
      )) : (
        <p className="settings-muted-text">{t('apiExamples.noExamples')}</p>
      )}
      {copyError ? <p className="settings-error-text">{copyError}</p> : null}
    </section>
  );
}
