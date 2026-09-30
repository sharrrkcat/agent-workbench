import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { BrushCleaning, ChevronDown, FileText, MoreHorizontal, ScanLine, Square, Trash2, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useModelsStore } from '../../store/useModelsStore';
import type { RuntimeJob } from '../../types/models';

export function runtimeBytes(value: number | null | undefined, unknown: string) {
  if (value == null) return unknown;
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  const exponent = value > 0 ? Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1) : 0;
  return `${(value / 1024 ** exponent).toLocaleString(undefined, { maximumFractionDigits: exponent ? 2 : 0 })} ${units[exponent]}`;
}

export function CacheJobResult({ job }: { job: RuntimeJob }) {
  const { t } = useTranslation('llm');
  if (!job.result) return null;
  return (
    <dl className="runtime-cache-result">
      {(['before', 'after'] as const).map((moment) => <div key={moment}>
        <dt>{t('storage.' + moment)}</dt>
        <dd>{runtimeBytes(job.result?.[moment]?.logical_bytes, t('storage.unknown'))}</dd>
        <dt>{t('storage.exclusive')}</dt>
        <dd>{runtimeBytes(job.result?.[moment]?.exclusive_bytes, t('storage.unknown'))}</dd>
      </div>)}
    </dl>
  );
}

export function RuntimeStoragePanel({ busy, active, activeView, onCleanup, onCancel, onShowLog }: {
  busy: boolean; activeView: boolean; active: RuntimeJob | undefined;
  onCleanup: (mode: 'prune' | 'clean') => Promise<RuntimeJob | void>;
  onCancel: (job: RuntimeJob) => void;
  onShowLog: (job: RuntimeJob) => void;
}) {
  const { t } = useTranslation('llm');
  const { storage, storageLoading, storageError, reloadStorage, jobs } = useModelsStore();
  const { confirm, confirmation } = useConfirmDialog(activeView);
  const [trackedId, setTrackedId] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const visit = useRef(0);
  const visible = useRef(activeView);
  visible.current = activeView;
  const activeCache = active?.version === null ? active : undefined;
  useEffect(() => {
    if (!activeView) {
      visit.current++;
      setTrackedId(null);
      setMenuOpen(false);
    }
  }, [activeView]);
  useEffect(() => {
    if (activeView && activeCache) setTrackedId(activeCache.id);
  }, [activeView, activeCache?.id]);
  const task = activeView ? activeCache || jobs.find((job) => job.id === trackedId) : undefined;
  const running = task?.state === 'queued' || task?.state === 'running';
  const stale = !!storage && jobs.some((job) => job.finished_at && Date.parse(job.finished_at) > Date.parse(storage.scanned_at));
  const cache = storage?.groups.find((group) => group.category === 'cache');
  const bytes = (value: number | null | undefined) => runtimeBytes(value, t('storage.unknown'));
  async function cleanup(mode: 'prune' | 'clean') {
    const currentVisit = visit.current;
    const job = await onCleanup(mode);
    if (job && visible.current && currentVisit === visit.current) setTrackedId(job.id);
  }
  return (
    <Card className="runtime-storage" role="region" aria-label={t('storage.title')} aria-busy={storageLoading}>
      <CardHeader>
        <CardTitle>{t('storage.title')}</CardTitle>
        <CardDescription>
          {storageLoading ? t('storage.scanning') : storage ? t('storage.lastScan', { time: new Date(storage.scanned_at).toLocaleString() }) : t('storage.manualScan')}
        </CardDescription>
        <CardAction>
          <Button type="button" variant="outline" disabled={busy || !!active || storageLoading} onClick={() => void reloadStorage().catch(() => undefined)}>
            <ScanLine data-icon="inline-start" />{t('storage.scan')}
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {storageError ? <Alert variant="destructive"><AlertDescription>{storageError}</AlertDescription></Alert> : null}
        {storage && !storage.complete ? <Alert className="runtime-storage-warning"><AlertDescription>{t('storage.incomplete')}</AlertDescription></Alert> : null}
        {stale ? <Badge className="self-start" variant="outline">{t('storage.stale')}</Badge> : null}
        {storage ? <dl className="runtime-storage-summary">
          <div><dt>{t('storage.totalUnique')}</dt><dd>{bytes(storage.totals.unique_bytes)}</dd></div>
          <div><dt>{t('storage.cacheSize')}</dt><dd>{bytes(cache?.logical_bytes)}</dd></div>
          <div><dt title={t('storage.estimateHint')}>{t('storage.reclaimable')}</dt><dd>{bytes(cache?.exclusive_bytes)}</dd></div>
        </dl> : !storageLoading ? <Empty className="runtime-storage-empty">
          <EmptyHeader><EmptyTitle>{t(storageError ? 'storage.unavailable' : 'storage.notScanned')}</EmptyTitle>
            <EmptyDescription>{t(storageError ? 'storage.retryScan' : 'storage.scanHint')}</EmptyDescription>
          </EmptyHeader>
        </Empty> : <div className="runtime-storage-summary" aria-hidden="true"><Skeleton className="h-14" /><Skeleton className="h-14" /><Skeleton className="h-14" /></div>}
        <div className="runtime-cache-actions">
          <Button type="button" disabled={busy || !!active} onClick={() => void cleanup('prune')} variant="outline">
            <BrushCleaning data-icon="inline-start" />{t('cachePrune')}
          </Button>
          <DropdownMenu open={activeView && menuOpen} onOpenChange={setMenuOpen}>
            <DropdownMenuTrigger render={<Button type="button" variant="ghost" size="icon" aria-label={t('cacheActions')} />}><MoreHorizontal /></DropdownMenuTrigger>
            <DropdownMenuContent align="end"><DropdownMenuGroup>
              <DropdownMenuItem variant="destructive" disabled={busy || !!active} onClick={async () => {
                const estimate = storage ? `${t('storage.reclaimable')}: ${bytes(cache?.exclusive_bytes)}${stale ? ` (${t('storage.stale')})` : ''}` : t('storage.notScanned');
                if (await confirm(`${estimate}\n\n${t('cacheCleanConsequence')}`, {
                  destructive: true, title: t('cacheCleanConfirm'), confirmLabel: t('cacheClean'),
                })) void cleanup('clean');
              }}><Trash2 />{t('cacheClean')}</DropdownMenuItem>
            </DropdownMenuGroup></DropdownMenuContent>
          </DropdownMenu>
        </div>
        {task ? <Alert className="runtime-cache-task" role="status" variant={task.state === 'failed' ? 'destructive' : 'default'}>
          <div className="runtime-cache-task-heading">
            <span>{t('runtimeOperations.' + task.operation)} · {t('jobStates.' + task.state)}</span>
            <div className="flex items-center gap-2">
              <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => onShowLog(task)}>
                <FileText data-icon="inline-start" />{t('runtimeDetails')}
              </Button>
              {running ? <Button type="button" disabled={busy || task.cancel_requested} onClick={() => onCancel(task)} variant="outline" size="sm">
                <Square data-icon="inline-start" />{t('cancelTask')}
              </Button> : <Button type="button" aria-label={t('dismissRuntimeResult')} onClick={() => setTrackedId(null)} variant="ghost" size="icon">
                <X />
              </Button>}
            </div>
          </div>
          {running ? <span>{t('runtimeStages.' + task.stage)}</span> : null}
          {task.state === 'failed' && task.error_code ? <span className="error-text">{task.error_code}</span> : null}
        </Alert> : null}
      </CardContent>
      {storage ? <CardFooter className="block">
        <Collapsible className="runtime-storage-details">
          <CollapsibleTrigger render={<Button type="button" variant="ghost" className="w-full justify-between" />}>
            {t('storage.details')}<ChevronDown data-icon="inline-end" />
          </CollapsibleTrigger>
          <CollapsibleContent>
            <Table className="runtime-storage-table">
              <TableHeader><TableRow>
                <TableHead>{t('storage.directory')}</TableHead>
                {['files', 'logical', 'unique', 'shared', 'exclusive'].map((key) => <TableHead key={key}>{t('storage.' + key)}</TableHead>)}
              </TableRow></TableHeader>
              <TableBody>{storage.groups.map((group) => <TableRow key={group.id}>
                <TableHead scope="row"><span>{group.category === 'runtime' ? t('coreRuntime') : t('storage.categories.' + group.category)}</span>
                  <code>{group.category === 'other' ? '' : group.relative_path}</code></TableHead>
                <TableCell>{group.file_count == null ? t('storage.unknown') : group.file_count.toLocaleString()}</TableCell>
                {(['logical_bytes', 'unique_bytes', 'shared_bytes', 'exclusive_bytes'] as const).map((key) => <TableCell key={key}>{bytes(group[key])}</TableCell>)}
              </TableRow>)}</TableBody>
            </Table>
            {storage.warnings.length ? <ul className="runtime-storage-warnings">
              {storage.warnings.map((warning, index) => <li key={index}><code>{warning.relative_path}</code>: {t('storage.warnings.' + warning.code)}</li>)}
            </ul> : null}
          </CollapsibleContent>
        </Collapsible>
      </CardFooter> : null}
      {confirmation}
    </Card>
  );
}
