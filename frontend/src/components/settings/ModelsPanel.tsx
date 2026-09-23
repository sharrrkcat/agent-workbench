import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select';
import { Field, FieldLabel } from '@/components/ui/field';
import { RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../api/models';
import { useModelsStore } from '../../store/useModelsStore';

import { ProfilesTab } from './models/ProfilesTab';
import { ProvidersTab } from './models/ProvidersTab';
import { LocalRuntimePanel } from './LocalRuntimePanel';
import { ExternalServicePanel } from './models/ExternalServicePanel';
import { useModelFeedback } from './models/useModelFeedback';

export function ModelsPanel() {
  const { t } = useTranslation('llm');
  const { profiles, settings, reloadRuntimes, loading, error: loadError, reload } = useModelsStore();
  const [tab, setTab] = useState<'profiles' | 'providers' | 'localRuntime' | 'service'>('profiles');
  const { busy, error, notice, run, setError } = useModelFeedback(reload);
  useEffect(() => {
    void reload().catch(() => undefined);
  }, [reload]);
  useEffect(() => {
    void reloadRuntimes().catch(() => undefined);
  }, [reloadRuntimes]);
  const chatProfiles = profiles.filter((profile) => profile.kind === 'llm' && profile.enabled);
  const feedback = (
    <div
      role="status"
      className={error || loadError ? 'error-text model-feedback' : 'success-text model-feedback'}
    >
      {error || loadError || notice}
    </div>
  );
  const editorProps = { busy, run, feedback, setError };
  return (
    <Tabs
      value={tab}
      onValueChange={setTab}
      render={<section className="settings-panel models-panel" aria-busy={busy || loading} />}
    >
      <div className="model-heading">
        <h2>{t('title')}</h2>
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={t('refresh')}
                disabled={busy || loading}
                onClick={() => void run(reload, false)}
              />
            }
          >
            <RefreshCw size={16} />
          </TooltipTrigger>
          <TooltipContent>{t('refresh')}</TooltipContent>
        </Tooltip>
      </div>
      {feedback}
      <div className="model-defaults">
        <Field>
          <FieldLabel>{t('defaultModel')}</FieldLabel>
          <Select
            value={settings?.default_model_profile_id || ''}
            disabled={busy || !settings}
            onValueChange={(selected) =>
              void run(() =>
                modelsApi.updateModelSettings({ default_model_profile_id: (selected ?? '') || null }),
              )
            }
            items={[
              { value: '', label: t('unconfigured') },
              ...chatProfiles.map((profile) => ({ value: profile.id, label: profile.name })),
            ]}
          >
            <SelectTrigger aria-label={t('defaultModel')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="">{t('unconfigured')}</SelectItem>
              {chatProfiles.map((profile) => (
                <SelectItem value={profile.id} key={profile.id}>
                  {profile.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field>
          <FieldLabel>{t('utilityModel')}</FieldLabel>
          <Select
            value={settings?.utility_model_profile_id || ''}
            disabled={busy || !settings}
            onValueChange={(selected) =>
              void run(() =>
                modelsApi.updateModelSettings({ utility_model_profile_id: (selected ?? '') || null }),
              )
            }
            items={[
              { value: '', label: t('unconfigured') },
              ...chatProfiles.map((profile) => ({ value: profile.id, label: profile.name })),
            ]}
          >
            <SelectTrigger aria-label={t('utilityModel')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="">{t('unconfigured')}</SelectItem>
              {chatProfiles.map((profile) => (
                <SelectItem value={profile.id} key={profile.id}>
                  {profile.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      </div>
      <TabsList className="model-tabs">
        {(['profiles', 'providers', 'localRuntime', 'service'] as const).map((value) => (
          <TabsTrigger value={value} key={value}>
            {t(value)}
          </TabsTrigger>
        ))}
      </TabsList>
      <TabsContent value="profiles" keepMounted hidden={tab !== 'profiles'}>
        <ProfilesTab {...editorProps} onOpenLocalRuntime={() => setTab('localRuntime')} />
      </TabsContent>
      <TabsContent value="providers" keepMounted hidden={tab !== 'providers'}>
        <ProvidersTab {...editorProps} />
      </TabsContent>
      <TabsContent value="localRuntime" keepMounted hidden={tab !== 'localRuntime'}>
        <LocalRuntimePanel activeView={tab === 'localRuntime'} />
      </TabsContent>
      <TabsContent value="service" keepMounted hidden={tab !== 'service'}>
        <ExternalServicePanel run={run} busy={busy} />
      </TabsContent>
    </Tabs>
  );
}
