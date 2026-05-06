import { RefreshCw, Zap } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { CapabilityConfig, LlmResolvedConfig, LlmTestResult } from '../../types';
import { ConfigForm } from './ConfigForm';
import type { ConfigValues } from './configUtils';

export function LlmSettingsPanel({
  config,
  values,
  onValuesChange,
  showConfig = true,
}: {
  config: CapabilityConfig;
  values: ConfigValues;
  onValuesChange: (values: ConfigValues) => void;
  showConfig?: boolean;
}) {
  const { getResolvedLlmConfig, testLlmConnection, testingLlm } = useWorkbenchStore();
  const [resolved, setResolved] = useState<LlmResolvedConfig | null>(null);
  const [testResult, setTestResult] = useState<LlmTestResult | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [localError, setLocalError] = useState('');

  useEffect(() => {
    let cancelled = false;
    void getResolvedLlmConfig().then((status) => {
      if (!cancelled) setResolved(status);
    });
    return () => {
      cancelled = true;
    };
  }, [getResolvedLlmConfig, config.updated_at]);

  async function runTest() {
    setLocalError('');
    const result = await testLlmConnection();
    setTestResult(result);
    if (result.models?.length) {
      setModels(result.models);
    }
  }

  async function refreshModels() {
    setLoadingModels(true);
    setLocalError('');
    try {
      const result = await api.listLlmModels();
      setModels(result.models.map((model) => model.id).filter(Boolean));
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : 'Failed to list models.');
    } finally {
      setLoadingModels(false);
    }
  }

  return (
    <div className="llm-settings-panel">
      {showConfig ? (
        <section className="detail-section">
          <h3>Connection</h3>
          <ConfigForm
            fields={config.config_schema || []}
            values={values}
            onChange={onValuesChange}
            emptyMessage="This capability has no configurable fields."
          />
        </section>
      ) : null}

      <section className="detail-section">
        <div className="detail-section-heading">
          <h3>Resolved LLM config</h3>
          <button className="settings-secondary-button" type="button" onClick={() => void refreshModels()} disabled={loadingModels || testingLlm}>
            <RefreshCw size={14} className={loadingModels ? 'spin' : ''} />
            {loadingModels ? 'Refreshing...' : 'Refresh models'}
          </button>
        </div>
        {resolved ? <ResolvedLlmConfig status={resolved} /> : <div className="settings-empty-state">Resolved config is unavailable.</div>}
        <div className="settings-button-row">
          <button className="settings-primary-button" type="button" disabled={testingLlm || loadingModels} onClick={() => void runTest()}>
            <Zap size={14} />
            {testingLlm ? 'Testing...' : 'Test connection'}
          </button>
        </div>
        {models.length ? (
          <label className="config-field settings-config-field" htmlFor="llm-model-select">
            <span>Available models</span>
            <select
              id="llm-model-select"
              value={String(values.model ?? '')}
              onChange={(event) => onValuesChange({ ...values, model: event.target.value })}
            >
              <option value="">Select model</option>
              {models.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
            <small>Choose a model, then Save to store it in the LLM capability config.</small>
          </label>
        ) : null}
        {testResult ? (
          <p className={testResult.success ? 'settings-success-text' : 'settings-error-text'}>
            {testResult.message}
            {testResult.models?.length ? ` Models: ${testResult.models.join(', ')}` : ''}
          </p>
        ) : null}
        {localError ? <p className="settings-error-text">{localError}</p> : null}
      </section>
    </div>
  );
}

function ResolvedLlmConfig({ status }: { status: LlmResolvedConfig }) {
  return (
    <dl className="settings-definition-grid">
      <div>
        <dt>Base URL</dt>
        <dd>{status.base_url || 'unset'}</dd>
      </div>
      <div>
        <dt>Model</dt>
        <dd>{status.model || 'unset'}</dd>
      </div>
      <div>
        <dt>Timeout</dt>
        <dd>{status.timeout ?? 'unset'}</dd>
      </div>
      <div>
        <dt>API key set</dt>
        <dd>{status.api_key_set ? 'yes' : 'no'}</dd>
      </div>
    </dl>
  );
}
