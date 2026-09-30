import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Field, FieldGroup, FieldLabel, FieldSet } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { LoadingStatus } from '@/components/ui/loading-status';
import { ChevronDown, Download, FileText, MoreHorizontal, RefreshCw, Save, Square, Trash2, Wrench } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../api/models';
import { useModelsStore } from '../../store/useModelsStore';
import type { ComponentId, RuntimeCatalog, RuntimeDownloadSettings, RuntimeInstallation, RuntimeJob } from '../../types/models';
import { CacheJobResult, RuntimeStoragePanel } from './RuntimeStoragePanel';
import { Feedback } from './resources/ResourceUI';

function RuntimePackageCard({ id, title, value, bundled, catalog, job, active, baseReady, busy, activeView, run, showLog }: {
  id?: ComponentId; title: string; value: RuntimeInstallation | null; bundled: string; catalog: RuntimeCatalog;
  job?: RuntimeJob; active?: RuntimeJob; baseReady: boolean; busy: boolean; activeView: boolean;
  run: (task: () => Promise<RuntimeJob | void>) => Promise<RuntimeJob | void>;
  showLog: (job: RuntimeJob) => Promise<void>;
}) {
  const { t } = useTranslation('llm');
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => { if (!activeView) setMenuOpen(false); }, [activeView]);
  const state = value?.state || (catalog.supported ? 'not_installed' : 'unsupported');
  const running = job?.state === 'queued' || job?.state === 'running';
  const update = !!id && state === 'installed' && value?.version !== bundled;
  const needsRepair = state === 'broken' || state === 'interrupted';
  const primary = running ? 'cancel' : !catalog.supported ? null : needsRepair ? 'repair' : state === 'not_installed' || update ? 'install' : null;
  const PrimaryIcon = primary === 'cancel' ? Square : primary === 'repair' ? Wrench : Download;
  const primaryLabel = t(primary === 'cancel' ? 'cancelTask' : primary === 'repair' ? 'repairRuntime' : update ? 'updateComponent' : 'installRuntime');
  const error = value?.error_code || (job?.state === 'failed' ? job.error_code : null);
  const canRemove = catalog.supported && state !== 'not_installed' && state !== 'unsupported';
  const hasMenu = !!job || canRemove;
  async function action(operation: 'install' | 'repair' | 'uninstall') {
    const next = await modelsApi.runtimeAction(operation, id);
    useModelsStore.getState().setJob(next);
    return next;
  }
  return (
    <Card className="runtime-package" role="group" aria-label={title}>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          <span>{title}</span>
          <Badge variant="outline">{state === 'not_installed' ? bundled : value?.version}</Badge>
          <Badge variant="outline">{catalog.platform}</Badge>
          <Badge variant="outline">{catalog.architecture}</Badge>
        </CardTitle>
        <CardDescription>{t(id ? 'dlssComponentSummary' : 'coreRuntimeSummary')}</CardDescription>
        <CardAction><Badge variant={needsRepair ? 'destructive' : 'secondary'}>{t('runtimeStates.' + state)}</Badge></CardAction>
      </CardHeader>
      {update || (id && !baseReady && catalog.supported) || running || error ? <CardContent className="flex flex-col gap-3">
        {update ? <span className="text-muted-foreground">{t('bundledVersion')}: {bundled}</span> : null}
        {id && !baseReady && catalog.supported ? <p className="text-muted-foreground">{t('coreRuntimeRequired')}</p> : null}
        {running ? <div className="runtime-progress" role="status">
          <span>{t('runtimeStages.' + job.stage)}</span>
          <progress aria-label={t('runtimeProgress')} value={job.progress_total ? job.progress_current : undefined} max={job.progress_total || undefined} />
        </div> : null}
        {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
      </CardContent> : null}
      {primary || hasMenu ? <CardFooter className="justify-end gap-2">
        {primary ? <Button type="button" disabled={busy || (running ? job.cancel_requested : !!active || !baseReady)}
          onClick={() => void run(async () => {
            if (primary !== 'cancel') return action(primary);
            const next = await modelsApi.cancelRuntimeJob(job!.id);
            useModelsStore.getState().setJob(next);
            return next;
          })} variant={running ? 'outline' : 'default'}>
          <PrimaryIcon data-icon="inline-start" />{primaryLabel}
        </Button> : null}
        {hasMenu ? <DropdownMenu open={activeView && menuOpen} onOpenChange={setMenuOpen}>
          <DropdownMenuTrigger render={<Button type="button" variant="ghost" size="icon" aria-label={t('runtimeActions')} />}>
            <MoreHorizontal />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end"><DropdownMenuGroup>
            {canRemove && primary !== 'repair' ? <DropdownMenuItem disabled={busy || !!active || !baseReady} onClick={() => void run(() => action('repair'))}>
              <Wrench />{t('repairRuntime')}
            </DropdownMenuItem> : null}
            {job ? <DropdownMenuItem disabled={busy} onClick={() => void run(() => showLog(job))}>
              <FileText />{t('runtimeLog')}
            </DropdownMenuItem> : null}
            {canRemove ? <DropdownMenuItem variant="destructive" disabled={busy || !!active} onClick={() => void run(() => action('uninstall'))}>
              <Trash2 />{t('uninstallRuntime')}
            </DropdownMenuItem> : null}
          </DropdownMenuGroup></DropdownMenuContent>
        </DropdownMenu> : null}
      </CardFooter> : null}
    </Card>
  );
}

export function LocalRuntimePanel({ activeView }: { activeView: boolean }) {
  const { t } = useTranslation('llm');
  const { localRuntimeSettings: local, catalog, installation, components, jobs, runtimeLoading, runtimeError, reloadRuntimes, setJob } = useModelsStore();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const [settings, setSettings] = useState<RuntimeDownloadSettings | null>(null);
  const [log, setLog] = useState<{ job: RuntimeJob; text: string } | null>(null);
  const logRequest = useRef(0);
  const active = jobs.find((job) => job.state === 'queued' || job.state === 'running');
  const jobLabel = (item: RuntimeJob) => [item.component_id ? t('dlssComponent') : item.version !== null ? t('coreRuntime') : t('storage.title'), t('runtimeOperations.' + item.operation)].join(' · ');
  useEffect(() => {
    setSettings(local?.download ?? null);
  }, [local?.download.http_proxy, local?.download.pypi_index_url, local?.download.pytorch_index_url, local?.download.github_release_proxy_url]);
  useEffect(() => { if (!activeView) { logRequest.current++; setLog(null); } }, [activeView]);
  async function run(task: () => Promise<RuntimeJob | void>) {
    setBusy(true);
    setError('');
    try { return await task(); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function showLog(job: RuntimeJob) {
    const request = ++logRequest.current;
    const value = await modelsApi.runtimeJobLog(job.id);
    if (request === logRequest.current) setLog({ job, text: value.text });
  }
  return (
    <div className="runtime-panel">
      <div className="model-toolbar">
        <h2>{t('runtimePackages')}</h2>
        <Button disabled={busy || runtimeLoading} onClick={() => void run(reloadRuntimes)} type="button" variant="ghost">
          <RefreshCw data-icon="inline-start" />{t('refreshRuntimeStatus')}
        </Button>
      </div>
      {error || runtimeError ? <Alert variant="destructive"><AlertDescription>{error || runtimeError}</AlertDescription></Alert> : null}
      <div className="runtime-packages">
        {catalog ? [
          { id: undefined, title: t('coreRuntime'), value: installation, bundled: catalog.version },
          ...components.map((component) => ({ id: component.component_id, title: t('dlssComponent'), value: component, bundled: component.bundled_version })),
        ].map((target) => <RuntimePackageCard key={target.id ?? 'base'} {...target} catalog={catalog}
          job={jobs.find((item) => item.version !== null && (item.component_id ?? undefined) === target.id)}
          active={active} baseReady={!target.id || installation?.state === 'installed'} busy={busy} activeView={activeView} run={run} showLog={showLog} />)
          : runtimeLoading ? <LoadingStatus /> : null}
      </div>
      <RuntimeStoragePanel activeView={activeView} busy={busy} active={active}
        onCleanup={(mode) => run(async () => { const job = await modelsApi.cleanupRuntimeCache(mode); setJob(job); return job; })}
        onCancel={(job) => void run(async () => setJob(await modelsApi.cancelRuntimeJob(job.id)))}
        onShowLog={(job) => void run(() => showLog(job))} />
      <div className="runtime-secondary">
        <Collapsible className="runtime-download-settings">
          <CollapsibleTrigger render={<Button type="button" variant="ghost" className="w-full justify-between" />}>
            {t('downloadSettings')}<ChevronDown data-icon="inline-end" />
          </CollapsibleTrigger>
          <CollapsibleContent keepMounted>
            {settings ? <form onSubmit={(event) => {
              event.preventDefault();
              void run(async () => {
                const next = await modelsApi.patchLocalRuntimeSettings({ download: settings });
                useModelsStore.setState({ localRuntimeSettings: next });
                setSaved(true);
              });
            }}>
              <FieldSet className="model-form" disabled={busy || !!active}>
                <FieldGroup className="grid gap-4 md:grid-cols-2">
                  {(Object.keys(settings) as Array<keyof RuntimeDownloadSettings>).map((key) => <Field key={key}>
                    <FieldLabel>{t('download.' + key)}</FieldLabel>
                    <Input type="url" value={settings[key] || ''} onChange={(e) => { setSaved(false); setSettings({ ...settings, [key]: e.target.value || null }); }} />
                  </Field>)}
                </FieldGroup>
                <div className="model-form-footer">
                  <Feedback error="" notice={saved ? t('runtimeSettingsSaved') : ''} className="w-auto" />
                  <Button type="submit"><Save data-icon="inline-start" />{t('save')}</Button>
                </div>
              </FieldSet>
            </form> : null}
          </CollapsibleContent>
        </Collapsible>
        <Collapsible className="runtime-task-history">
          <CollapsibleTrigger render={<Button type="button" variant="ghost" className="w-full justify-between" />}>
            <span>{t('runtimeHistory')}{jobs.length ? ` (${jobs.length})` : ''}</span><ChevronDown data-icon="inline-end" />
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="runtime-history">
              {jobs.length ? jobs.map((job) => <div className="runtime-history-row" key={job.id}>
                <div className="model-identity"><span>{jobLabel(job)}</span><small>{new Date(job.created_at).toLocaleString()}</small></div>
                <Badge variant={job.state === 'failed' ? 'destructive' : 'secondary'}>{t('jobStates.' + job.state)}</Badge>
                <Button type="button" disabled={busy} onClick={() => void run(() => showLog(job))} variant="ghost" size="sm">
                  <FileText data-icon="inline-start" />{t('runtimeLog')}
                </Button>
              </div>) : <p className="text-muted-foreground">{t('runtimeHistoryEmpty')}</p>}
            </div>
          </CollapsibleContent>
        </Collapsible>
      </div>
      <Dialog open={activeView && !!log} onOpenChange={(open) => { if (!open) { logRequest.current++; setLog(null); } }}>
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader><DialogTitle>{t('runtimeLog')}</DialogTitle></DialogHeader>
          <div className="min-h-0 overflow-y-auto overscroll-contain">
            {log ? <div className="flex flex-col gap-4">
              <div className="model-toolbar">
                <span>{jobLabel(log.job)}</span>
                <Button disabled={busy} onClick={() => void run(() => showLog(log.job))} type="button" variant="ghost">
                  <RefreshCw data-icon="inline-start" />{t('refresh')}
                </Button>
              </div>
              <CacheJobResult job={jobs.find((job) => job.id === log.job.id) || log.job} />
              <pre className="runtime-log">{log.text || t('emptyLog')}</pre>
            </div> : null}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
