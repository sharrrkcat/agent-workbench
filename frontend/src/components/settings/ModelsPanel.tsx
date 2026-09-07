import { RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../api/models';
import { useModelsStore } from '../../store/useModelsStore';
import { RuntimesPanel } from './RuntimesPanel';
import { Field, Icon } from './models/fields';
import { ProfilesTab } from './models/ProfilesTab';
import { ConnectionsTab } from './models/ConnectionsTab';
import { ExternalServicePanel } from './models/ExternalServicePanel';
import { useModelFeedback } from './models/useModelFeedback';

export function ModelsPanel() {
  const { t } = useTranslation('llm');
  const { profiles, settings, reloadRuntimes, loading, error: loadError, reload } = useModelsStore();
  const [tab, setTab] = useState<'profiles' | 'providers' | 'runtimes' | 'service'>('profiles');
  const { busy, error, notice, run, setError } = useModelFeedback(reload);
  useEffect(() => {
    void reload().catch(() => undefined);
  }, [reload]);
  useEffect(() => {
    void reloadRuntimes().catch(() => undefined);
  }, [reloadRuntimes]);
  const chatProfiles = profiles.filter((profile) => profile.kind === 'llm' && profile.enabled);
  const feedback = (
    <div role="status" className={error || loadError ? 'error-text model-feedback' : 'success-text model-feedback'}>
      {error || loadError || notice}
    </div>
  );
  const editorProps = { busy, run, feedback, setError };
  return (
    <section className="settings-panel models-panel" aria-busy={busy || loading}>
      <div className="model-heading">
        <h2>{t('title')}</h2>
        <Icon label={t('refresh')} disabled={busy || loading} onClick={() => void run(reload, false)}>
          <RefreshCw size={16} />
        </Icon>
      </div>
      {feedback}
      <div className="model-defaults">
        <Field label={t('defaultModel')}>
          <select
            aria-label={t('defaultModel')}
            value={settings?.default_model_profile_id || ''}
            disabled={busy || !settings}
            onChange={(event) =>
              void run(() => modelsApi.updateModelSettings({ default_model_profile_id: event.target.value || null }))
            }
          >
            <option value="">{t('unconfigured')}</option>
            {chatProfiles.map((profile) => (
              <option value={profile.id} key={profile.id}>
                {profile.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t('utilityModel')}>
          <select
            aria-label={t('utilityModel')}
            value={settings?.utility_model_profile_id || ''}
            disabled={busy || !settings}
            onChange={(event) =>
              void run(() => modelsApi.updateModelSettings({ utility_model_profile_id: event.target.value || null }))
            }
          >
            <option value="">{t('unconfigured')}</option>
            {chatProfiles.map((profile) => (
              <option value={profile.id} key={profile.id}>
                {profile.name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <div className="model-tabs" role="tablist">
        {(['profiles', 'providers', 'runtimes', 'service'] as const).map((value) => (
          <button role="tab" aria-selected={tab === value} key={value} onClick={() => setTab(value)}>
            {t(value)}
          </button>
        ))}
      </div>
      <div hidden={tab !== 'profiles'}>
        <ProfilesTab {...editorProps} onOpenRuntimes={() => setTab('runtimes')} />
      </div>
      <div hidden={tab !== 'providers'}>
        <ConnectionsTab {...editorProps} />
      </div>
      <div hidden={tab !== 'service'}>
        <ExternalServicePanel run={run} busy={busy} />
      </div>
      {tab === 'runtimes' ? <RuntimesPanel /> : null}
    </section>
  );
}
