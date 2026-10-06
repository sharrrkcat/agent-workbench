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
import { Separator } from '@/components/ui/separator';
import { RefreshCw } from 'lucide-react';
import { useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../api/models';
import { useModelsStore } from '../../store/useModelsStore';
import { modelKinds, type ModelKind } from '../../types/models';

import { ProfilesTab } from './models/ProfilesTab';
import { ProvidersTab } from './models/ProvidersTab';
import { LocalRuntimePanel } from './LocalRuntimePanel';
import { ExternalServicePanel } from './models/ExternalServicePanel';
import { useModelFeedback } from './models/useModelFeedback';
import { SettingsView } from './SettingsView';
import { settingsRouteUrl, type ModelView, type SettingsNavigate } from './navigation';
import { Feedback, useSettingsLeaveGuard } from './resources/ResourceUI';

export function ModelsPanel({ view, onNavigate, listOnlyKind, onOpenEditor }: {
  view: ModelView; onNavigate: SettingsNavigate; listOnlyKind: ModelKind | null; onOpenEditor: () => void;
}) {
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
  const feedback = <Feedback error={error || loadError} notice={notice} />;
  const editorProps = { busy, run, feedback, setError };
  return (
    <section className="settings-panel models-panel" aria-busy={busy || loading}>
      {view === 'dashboard' ? <div className="model-heading">
        <p className="text-muted-foreground">{t('viewHelp.dashboard')}</p>
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
      </div> : null}
      {feedback}
      <SettingsView active={view === 'dashboard'}>
        <FieldSet className="w-full max-w-3xl">
          <FieldLegend>{t('defaultModels')}</FieldLegend>
          <FieldGroup className="grid gap-4 md:grid-cols-2">
            <Field>
              <FieldLabel>{t('defaultModel')}</FieldLabel>
              <Select
                key={String(view === 'dashboard')}
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
                key={String(view === 'dashboard')}
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
        <Separator className="max-w-3xl" />
        <FieldSet className="w-full max-w-3xl">
          <FieldLegend>{t('service')}</FieldLegend>
          <ExternalServicePanel run={run} busy={busy} />
        </FieldSet>
      </SettingsView>
      {modelKinds.map((kind) => (
        <SettingsView key={kind} active={view === kind}>
          <ProfilesTab
            {...editorProps}
            kind={kind}
            editorVisible={listOnlyKind !== kind}
            onOpenEditor={onOpenEditor}
            onOpenLocalRuntime={() =>
              void onNavigate(settingsRouteUrl({ section: 'models', view: 'localRuntime' }))
            }
          />
        </SettingsView>
      ))}
      <SettingsView active={view === 'providers'}>
        <ProvidersTab {...editorProps} />
      </SettingsView>
      <SettingsView active={view === 'localRuntime'}>
        <LocalRuntimePanel activeView={view === 'localRuntime'} />
      </SettingsView>
    </section>
  );
}
