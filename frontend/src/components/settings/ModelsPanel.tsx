import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectGroup,
  SelectItem,
} from '@/components/ui/select';
import { Field, FieldLabel, FieldSet, FieldLegend, FieldGroup } from '@/components/ui/field';
import { RefreshCw } from 'lucide-react';
import { useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../api/models';
import { useModelsStore } from '../../store/useModelsStore';

import { ProfilesTab } from './models/ProfilesTab';
import { ProvidersTab } from './models/ProvidersTab';
import { LocalRuntimePanel } from './LocalRuntimePanel';
import { ExternalServicePanel } from './models/ExternalServicePanel';
import { useModelFeedback } from './models/useModelFeedback';
import { SettingsView } from './SettingsView';
import { settingsRouteUrl, type ModelView, type SettingsNavigate } from './navigation';
import { useSettingsLeaveGuard } from './resources/ResourceUI';

export function ModelsPanel({ view, onNavigate }: { view: ModelView; onNavigate: SettingsNavigate }) {
  const { t } = useTranslation('llm');
  const { profiles, settings, reloadRuntimes, loading, error: loadError, reload } = useModelsStore();
  const { busy, error, notice, run, setError } = useModelFeedback(reload);
  useSettingsLeaveGuard(useCallback(async () => !busy, [busy]));
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
    <section className="settings-panel models-panel" aria-busy={busy || loading}>
      <div className="model-heading">
        <p className="text-muted-foreground">{t('viewHelp.' + view)}</p>
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
            <RefreshCw data-icon="inline-start" />
          </TooltipTrigger>
          <TooltipContent>{t('refresh')}</TooltipContent>
        </Tooltip>
      </div>
      {feedback}
      <SettingsView active={view === 'profiles'}>
        <FieldSet className="model-defaults">
          <FieldLegend>{t('defaultModels')}</FieldLegend>
          <FieldGroup className="grid gap-4 md:grid-cols-2">
            <Field>
              <FieldLabel>{t('defaultModel')}</FieldLabel>
              <Select
                key={String(view === 'profiles')}
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
                  <SelectGroup>
                    <SelectItem value="">{t('unconfigured')}</SelectItem>
                    {chatProfiles.map((profile) => (
                      <SelectItem value={profile.id} key={profile.id}>
                        {profile.name}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
            <Field>
              <FieldLabel>{t('utilityModel')}</FieldLabel>
              <Select
                key={String(view === 'profiles')}
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
                  <SelectGroup>
                    <SelectItem value="">{t('unconfigured')}</SelectItem>
                    {chatProfiles.map((profile) => (
                      <SelectItem value={profile.id} key={profile.id}>
                        {profile.name}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
          </FieldGroup>
        </FieldSet>
        <ProfilesTab
          {...editorProps}
          onOpenLocalRuntime={() =>
            void onNavigate(settingsRouteUrl({ section: 'models', view: 'localRuntime' }))
          }
        />
      </SettingsView>
      <SettingsView active={view === 'providers'}>
        <ProvidersTab {...editorProps} />
      </SettingsView>
      <SettingsView active={view === 'localRuntime'}>
        <LocalRuntimePanel activeView={view === 'localRuntime'} />
      </SettingsView>
      <SettingsView active={view === 'service'}>
        <ExternalServicePanel run={run} busy={busy} />
      </SettingsView>
    </section>
  );
}
