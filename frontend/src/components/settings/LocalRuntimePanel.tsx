import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Switch } from '@/components/ui/switch';
import { Field, FieldLabel, FieldSet } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Download, FileText, RefreshCw, Save, Square, Trash2, Wrench } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../api/models';
import { useModelsStore } from '../../store/useModelsStore';
import type { RuntimeDownloadSettings, RuntimeJob } from '../../types/models';

import { CacheJobResult, RuntimeStoragePanel } from './RuntimeStoragePanel';

export function LocalRuntimePanel({ activeView }: { activeView: boolean }) {
  const { t } = useTranslation('llm');
  const {
    localRuntimeSettings: local,
    catalog,
    installation,
    jobs,
    reload,
    runtimeLoading,
    runtimeError,
    reloadRuntimes,
    reloadStorage,
    storageLoading,
    setJob,
  } = useModelsStore();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [settings, setSettings] = useState<RuntimeDownloadSettings | null>(null);
  const [log, setLog] = useState<{ job: RuntimeJob; text: string } | null>(null);
  const active = jobs.find((job) => job.state === 'queued' || job.state === 'running');
  const job = jobs.find((item) => item.version !== null);
  const running = job?.state === 'queued' || job?.state === 'running';
  const state = installation?.state || (catalog?.supported ? 'not_installed' : 'unsupported');
  const jobLabel = (item: RuntimeJob) => t('runtimeOperations.' + item.operation);
  useEffect(() => {
    setSettings(local?.download ?? null);
  }, [
    local?.download.http_proxy,
    local?.download.pypi_index_url,
    local?.download.pytorch_index_url,
    local?.download.github_release_proxy_url,
  ]);
  async function run(task: () => Promise<unknown>) {
    setBusy(true);
    setError('');
    try {
      await task();
      await reloadRuntimes();
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function showLog(job: RuntimeJob) {
    const value = await modelsApi.runtimeJobLog(job.id);
    setLog({ job, text: value.text });
  }
  return (
    <div className="runtime-panel">
      <div className="model-toolbar">
        <h3>{t('localRuntime')}</h3>
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                aria-label={t('refresh')}
                disabled={busy || runtimeLoading || storageLoading}
                onClick={() => void run(reloadStorage)}
                type="button"
                variant="ghost"
                size="icon"
              />
            }
          >
            <RefreshCw data-icon="inline-start" />
          </TooltipTrigger>
          <TooltipContent>{t('refresh')}</TooltipContent>
        </Tooltip>
      </div>
      {error || runtimeError ? (
        <p role="alert" className="error-text">
          {error || runtimeError}
        </p>
      ) : null}

      <Field orientation="horizontal" disabled={busy || !!active || !local}>
        <Switch
          checked={local?.enabled ?? true}
          disabled={busy || !!active || !local}
          onCheckedChange={(enabled) => void run(() => modelsApi.patchLocalRuntimeSettings({ enabled }))}
        />
        <FieldLabel>{t('enableLocalRuntime')}</FieldLabel>
      </Field>
      {catalog ? (
        <div className="runtime-row">
          <div className="model-identity">
            <strong>{t('localInstallation')}</strong>
            <small>
              {state === 'not_installed' ? catalog.version : (installation?.version ?? catalog.version)} /{' '}
              {catalog.platform} / {catalog.architecture}
            </small>
          </div>
          <div className="runtime-progress">
            <span>{t('runtimeStates.' + state)}</span>
            {job ? (
              <small>
                {t('jobStates.' + job.state)}: {t('runtimeStages.' + job.stage)}
              </small>
            ) : null}
            {running ? (
              <progress
                aria-label={t('runtimeProgress')}
                value={job.progress_total ? job.progress_current : undefined}
                max={job.progress_total || undefined}
              />
            ) : null}
            {installation?.error_code || job?.error_code ? (
              <code className="error-text">{installation?.error_code || job?.error_code}</code>
            ) : null}
          </div>
          <div className="model-actions">
            {running ? (
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button
                      type="button"
                      aria-label={t('cancelTask')}
                      disabled={busy || job.cancel_requested}
                      onClick={() => void run(async () => setJob(await modelsApi.cancelRuntimeJob(job.id)))}
                      variant="ghost"
                      size="icon"
                    />
                  }
                >
                  <Square data-icon="inline-start" />
                </TooltipTrigger>
                <TooltipContent>{t('cancelTask')}</TooltipContent>
              </Tooltip>
            ) : (
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button
                      type="button"
                      aria-label={t('installRuntime')}
                      disabled={busy || !!active || !catalog.supported || state !== 'not_installed'}
                      onClick={() => void run(async () => setJob(await modelsApi.runtimeAction('install')))}
                      variant="ghost"
                      size="icon"
                    />
                  }
                >
                  <Download data-icon="inline-start" />
                </TooltipTrigger>
                <TooltipContent>{t('installRuntime')}</TooltipContent>
              </Tooltip>
            )}
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    type="button"
                    aria-label={t('repairRuntime')}
                    disabled={busy || !!active || !catalog.supported || state === 'not_installed'}
                    onClick={() => void run(async () => setJob(await modelsApi.runtimeAction('repair')))}
                    variant="ghost"
                    size="icon"
                  />
                }
              >
                <Wrench data-icon="inline-start" />
              </TooltipTrigger>
              <TooltipContent>{t('repairRuntime')}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    type="button"
                    aria-label={t('uninstallRuntime')}
                    disabled={busy || !!active || !catalog.supported || state === 'not_installed'}
                    onClick={() => void run(async () => setJob(await modelsApi.runtimeAction('uninstall')))}
                    variant="ghost"
                    size="icon"
                  />
                }
              >
                <Trash2 data-icon="inline-start" />
              </TooltipTrigger>
              <TooltipContent>{t('uninstallRuntime')}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    type="button"
                    aria-label={t('runtimeLog')}
                    disabled={busy || !job}
                    onClick={() => job && void run(() => showLog(job))}
                    variant="ghost"
                    size="icon"
                  />
                }
              >
                <FileText data-icon="inline-start" />
              </TooltipTrigger>
              <TooltipContent>{t('runtimeLog')}</TooltipContent>
            </Tooltip>
          </div>
        </div>
      ) : null}
      <p>{t('runtimeReuseHint')}</p>
      <RuntimeStoragePanel
        activeView={activeView}
        busy={busy}
        active={active}
        onCleanup={(mode) => run(async () => setJob(await modelsApi.cleanupRuntimeCache(mode)))}
        onCancel={(job) => void run(async () => setJob(await modelsApi.cancelRuntimeJob(job.id)))}
      />
      <Collapsible className="runtime-download-settings">
        <CollapsibleTrigger render={<Button type="button" variant="ghost" className="justify-start" />}>
          {t('downloadSettings')}
        </CollapsibleTrigger>
        <CollapsibleContent keepMounted>
          {settings ? (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                void run(async () =>
                  setSettings((await modelsApi.patchLocalRuntimeSettings({ download: settings })).download),
                );
              }}
            >
              <FieldSet className="model-form" disabled={busy || !!active}>
                {(Object.keys(settings) as Array<keyof RuntimeDownloadSettings>).map((key) => (
                  <Field key={key} className="settings-field">
                    <FieldLabel>{t('download.' + key)}</FieldLabel>
                    <Input
                      type="url"
                      value={settings[key] || ''}
                      onChange={(e) => setSettings({ ...settings, [key]: e.target.value || null })}
                    />
                  </Field>
                ))}
                <div className="model-form-footer">
                  <Button type="submit" variant="default">
                    <Save data-icon="inline-start" />
                    {t('save')}
                  </Button>
                </div>
              </FieldSet>
            </form>
          ) : null}
        </CollapsibleContent>
      </Collapsible>
      {jobs.length ? (
        <Collapsible>
          <CollapsibleTrigger render={<Button type="button" variant="ghost" className="justify-start" />}>
            {t('runtimeHistory')}
          </CollapsibleTrigger>
          <CollapsibleContent keepMounted>
            <div className="runtime-history">
              {jobs.map((job) => (
                <div className="model-row" key={job.id}>
                  <span>
                    {jobLabel(job)}
                    <small>{new Date(job.created_at).toLocaleString()}</small>
                  </span>
                  <span>{t('jobStates.' + job.state)}</span>
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <Button
                          type="button"
                          aria-label={t('runtimeLog')}
                          disabled={busy}
                          onClick={() => void run(() => showLog(job))}
                          variant="ghost"
                          size="icon"
                        />
                      }
                    >
                      <FileText data-icon="inline-start" />
                    </TooltipTrigger>
                    <TooltipContent>{t('runtimeLog')}</TooltipContent>
                  </Tooltip>
                </div>
              ))}
            </div>
          </CollapsibleContent>
        </Collapsible>
      ) : null}
      <Dialog
        open={activeView && !!log}
        onOpenChange={(open) => {
          if (!open) (() => setLog(null))();
        }}
      >
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{t('runtimeLog')}</DialogTitle>
          </DialogHeader>
          <div className="min-h-0 overflow-y-auto overscroll-contain">
            {log ? (
              <>
                <div className="model-toolbar">
                  <span>{jobLabel(log.job)}</span>
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <Button
                          aria-label={t('refresh')}
                          disabled={busy}
                          onClick={() => void run(() => showLog(log.job))}
                          type="button"
                          variant="ghost"
                          size="icon"
                        />
                      }
                    >
                      <RefreshCw data-icon="inline-start" />
                    </TooltipTrigger>
                    <TooltipContent>{t('refresh')}</TooltipContent>
                  </Tooltip>
                </div>
                <CacheJobResult job={jobs.find((job) => job.id === log.job.id) || log.job} />
                <pre className="runtime-log">{log.text || t('emptyLog')}</pre>
              </>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
