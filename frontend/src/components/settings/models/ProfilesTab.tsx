import { Card, CardHeader, CardTitle, CardDescription, CardAction, CardContent } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { ResourceEmpty } from '../resources/ResourceUI';
import { useSettingsView } from '../SettingsView';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Activity, Copy, FileText, Pencil, Play, Plus, RefreshCw, Square, Trash2 } from 'lucide-react';
import { useState } from 'react';

import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import { useModelsStore } from '../../../store/useModelsStore';
import type { ModelKind, SiglipTower } from '../../../types/models';

import type { ModelFeedbackProps } from './types';
import { newModel } from './profileDefaults';
import { ProfileEditor, type ProfileDraft } from './ProfileEditor';
import { SiglipStatus, TowerActionMenu } from './SiglipControls';

export function ProfilesTab({
  kind,
  run,
  busy,
  feedback,
  setError,
  onOpenLocalRuntime,
  editorVisible,
  onOpenEditor,
}: ModelFeedbackProps & { kind: ModelKind; onOpenLocalRuntime: () => void; editorVisible: boolean; onOpenEditor: () => void }) {
  const { t } = useTranslation('llm');
  const activeView = useSettingsView();
  const { profiles, providers, statuses, setStatus, loading, reload } = useModelsStore();
  const [model, setModel] = useState<ProfileDraft | null>(null);
  const disabled = busy || loading;
  const [processLog, setProcessLog] = useState<{ title: string; text: string } | null>(null);
  const openLog = (id: string, tower?: SiglipTower) => run(async () => {
    const { text } = await modelsApi.getModelLog(id, tower);
    setProcessLog({ title: tower ? t('siglip.log.' + tower) : t('processLog'), text });
  }, false);
  const statusAction = (id: string, action: 'load' | 'unload' | 'health', tower?: SiglipTower) =>
    run(async () => {
      try {
        setStatus(id, await modelsApi.modelAction(id, action, tower));
      } finally {
        setStatus(id, await modelsApi.getModelStatus(id));
      }
    }, false);
  return (
    <>
      <div className="model-toolbar">
        <div className="model-actions">
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={t('refresh')}
                  disabled={disabled}
                  onClick={() => void run(reload, false)}
                />
              }
            >
              <RefreshCw data-icon="inline-start" />
            </TooltipTrigger>
            <TooltipContent>{t('refresh')}</TooltipContent>
          </Tooltip>
          <Button
            disabled={disabled}
            onClick={() => {
              setError('');
              onOpenEditor();
              setModel({ value: newModel(kind) });
            }}
            type="button"
            variant="outline"
          >
            <Plus data-icon="inline-start" />
            {t('addModel')}
          </Button>
        </div>
      </div>
      <div className="model-list gap-4">
        {profiles
          .filter((p) => p.kind === kind)
          .map((p) => {
            const status = statuses[p.id];
            const providerID = p.source?.type === 'provider' ? p.source.provider_profile_id : null;
            const sourceName = p.source?.type === 'local' ? t('localRuntime')
              : providers.find((provider) => provider.id === providerID)?.name ?? t('unconfigured');
            return (
              <Card className="model-profile-card min-w-0" role="group" aria-label={p.name} key={p.id}>
                <CardHeader className="flex min-w-0 flex-wrap items-center gap-4">
                  <Switch checked={p.enabled} aria-label={t('modelEnabled', { name: p.name })}
                    disabled={disabled}
                    onCheckedChange={(enabled) => void run(() => modelsApi.patchModelProfile(p.id, { enabled }))} />
                  <div className="model-identity">
                    <div className="flex min-w-0 flex-wrap items-center gap-2 [overflow-wrap:anywhere]">
                      <CardTitle>{p.name}</CardTitle>
                      <Badge variant="outline" className="h-auto min-h-5 max-w-full whitespace-normal [overflow-wrap:anywhere]">{sourceName}</Badge>
                    </div>
                    <CardDescription><code>{p.alias}</code></CardDescription>
                  </div>
                  <Badge variant="secondary">
                    {p.enabled ? t('states.' + (status?.state || 'unknown')) : t('disabled')}
                  </Badge>
                  <CardAction className="model-actions self-center max-lg:basis-full max-lg:justify-end">
                    {p.source?.type === 'local' ? (
                      <>
                        <Tooltip>
                          <TooltipTrigger
                            render={
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                aria-label={t('health')}
                                disabled={disabled || !p.enabled || !p.source}
                                onClick={() => void statusAction(p.id, 'health')}
                              />
                            }
                          >
                            <Activity data-icon="inline-start" />
                          </TooltipTrigger>
                          <TooltipContent>{t('health')}</TooltipContent>
                        </Tooltip>
                        {p.kind === 'image_embedding' ? (
                          <TowerActionMenu action="load" disabled={disabled || !p.enabled}
                            onSelect={(tower) => void statusAction(p.id, 'load', tower)} />
                        ) : <Tooltip>
                          <TooltipTrigger
                            render={
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                aria-label={t('load')}
                                disabled={disabled || !p.enabled || !p.source}
                                onClick={() => void statusAction(p.id, 'load')}
                              />
                            }
                          >
                            <Play data-icon="inline-start" />
                          </TooltipTrigger>
                          <TooltipContent>{t('load')}</TooltipContent>
                        </Tooltip>}
                        <Tooltip>
                          <TooltipTrigger
                            render={
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                aria-label={status?.unload_supported ? t('unload') : t('unloadUnsupported')}
                                disabled={
                                  disabled ||
                                  !status?.unload_supported ||
                                  !!status.active ||
                                  !!status.queued ||
                                  (!!status.runtime && status.runtime.install_state !== 'installed')
                                }
                                onClick={() => void statusAction(p.id, 'unload')}
                              />
                            }
                          >
                            <Square data-icon="inline-start" />
                          </TooltipTrigger>
                          <TooltipContent>
                            {status?.unload_supported ? t('unload') : t('unloadUnsupported')}
                          </TooltipContent>
                        </Tooltip>
                        {p.kind === 'image_embedding' ? (
                          <TowerActionMenu action="log" disabled={disabled}
                            onSelect={(tower) => void openLog(p.id, tower)} />
                        ) : <Tooltip>
                          <TooltipTrigger
                            render={
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                aria-label={t('processLog')}
                                disabled={disabled}
                                onClick={() => void openLog(p.id)}
                              />
                            }
                          >
                            <FileText data-icon="inline-start" />
                          </TooltipTrigger>
                          <TooltipContent>{t('processLog')}</TooltipContent>
                        </Tooltip>}
                      </>
                    ) : null}
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            aria-label={t('edit')}
                            disabled={disabled}
                            onClick={() => {
                              const { id, created_at: _c, updated_at: _u, ...value } = p;
                              setError('');
                              onOpenEditor();
                              setModel({ id, value });
                            }}
                          />
                        }
                      >
                        <Pencil data-icon="inline-start" />
                      </TooltipTrigger>
                      <TooltipContent>{t('edit')}</TooltipContent>
                    </Tooltip>
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            aria-label={t('duplicate')}
                            disabled={disabled}
                            onClick={() => {
                              const { id: _id, created_at: _c, updated_at: _u, ...value } = p;
                              setError('');
                              onOpenEditor();
                              setModel({
                                value: { ...value, alias: p.alias + '-copy', name: p.name + ' ' + t('copy') },
                              });
                            }}
                          />
                        }
                      >
                        <Copy data-icon="inline-start" />
                      </TooltipTrigger>
                      <TooltipContent>{t('duplicate')}</TooltipContent>
                    </Tooltip>
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            aria-label={t('delete')}
                            disabled={disabled}
                            onClick={() => void run(() => modelsApi.deleteModelProfile(p.id))}
                          />
                        }
                      >
                        <Trash2 data-icon="inline-start" />
                      </TooltipTrigger>
                      <TooltipContent>{t('delete')}</TooltipContent>
                    </Tooltip>
                  </CardAction>
                </CardHeader>
                <CardContent className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
                  {p.source?.type === 'provider' ? <small>{t('recentRequestState')}</small> : null}
                  {p.source?.type === 'local' ? <small>
                    {t('residency')}: {t('residencies.' + (status?.residency || 'unknown'))}
                  </small> : null}
                  <small>{t('active')}: {status?.active || 0} / {t('queued')}: {status?.queued || 0}</small>
                  {status?.error_code && !status.runtime ? (
                    <code className="error-text">{status.error_code}</code>
                  ) : null}
                  {status?.runtime && (status.runtime.device_name || status.runtime.gpu_layers_loaded != null
                    || status.error_code || status.runtime.install_state !== 'installed') ? (
                    <div className="model-runtime-state">
                      {status.runtime.device_name ? <span>{status.runtime.device_name}</span> : null}
                      {status.runtime.gpu_layers_loaded != null ? (
                        <span>
                          {t('gpuOffloaded', {
                            loaded: status.runtime.gpu_layers_loaded,
                            total: status.runtime.gpu_layers_total,
                          })}
                        </span>
                      ) : null}
                      {status.error_code ? <code className="error-text">{status.error_code}</code> : null}
                      {status.runtime.install_state !== 'installed' ? (
                        <Button
                          type="button"
                          onClick={() => onOpenLocalRuntime()}
                          variant="ghost"
                          className="text-button"
                        >
                          {t('manageLocalRuntime')}
                        </Button>
                      ) : null}
                    </div>
                  ) : null}
                  {status?.towers ? <SiglipStatus towers={status.towers} /> : null}
                </CardContent>
              </Card>
            );
          })}
        {!loading && !profiles.some((p) => p.kind === kind) ? (
          <ResourceEmpty>{t('emptyModels')}</ResourceEmpty>
        ) : null}
      </div>
      <Dialog
        open={activeView && processLog !== null}
        onOpenChange={(open) => {
          if (!open) (() => setProcessLog(null))();
        }}
      >
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{processLog?.title ?? t('processLog')}</DialogTitle>
          </DialogHeader>
          <div className="min-h-0 overflow-y-auto overscroll-contain">
            <pre className="runtime-log">{processLog?.text || t('emptyLog')}</pre>
          </div>
        </DialogContent>
      </Dialog>
      <ProfileEditor
        visible={editorVisible}
        model={model}
        setModel={setModel}
        run={run}
        busy={busy}
        feedback={feedback}
        setError={setError}
      />
    </>
  );
}
