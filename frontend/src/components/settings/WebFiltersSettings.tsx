import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, RefreshCw, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Item, ItemActions, ItemContent, ItemDescription, ItemGroup, ItemTitle } from '@/components/ui/item';
import { LoadingStatus } from '@/components/ui/loading-status';
import { Separator } from '@/components/ui/separator';
import { ApiError } from '@/api/http';
import { toolsApi } from '@/api/tools';
import type { WebFilterSettings, WebSubscription, WebFilterIssue } from '@/types/tools';
import type { ConfirmAction } from '@/hooks/useConfirmDialog';
import { errorText, Feedback, ResourceEmpty, useResourceTask } from './resources/ResourceUI';

export function useWebFilters() {
  const { t } = useTranslation('settings');
  const [settings, setSettings] = useState<WebFilterSettings | null>(null);
  const [rules, setRules] = useState('');
  const [adding, setAdding] = useState<{ name: string; url: string } | null>(null);
  const [invalidLine, setInvalidLine] = useState<number | null>(null);
  const [reload, setReload] = useState(0);
  const task = useResourceTask((error) => {
    if (error instanceof ApiError && error.code === 'WEB_FILTER_RULE_INVALID') {
      const line = Number(error.details.line);
      setInvalidLine(line);
      return t('webFilters.invalidRule', { line });
    }
    if (error instanceof ApiError && error.code === 'WEB_SUBSCRIPTION_EXISTS') return t('webFilters.duplicate');
    return errorText(error);
  });
  const { setError } = task;
  useEffect(() => {
    let live = true;
    setError('');
    void toolsApi.getWebFilters().then((value) => {
      if (live) { setSettings(value); setRules(value.custom_rules); }
    }).catch((error) => { if (live) setError(errorText(error)); });
    return () => { live = false; };
  }, [reload, setError]);

  function replaceSubscription(value: WebSubscription) {
    setSettings((current) => current && { ...current, subscriptions: current.subscriptions.some((row) => row.id === value.id)
      ? current.subscriptions.map((row) => row.id === value.id ? value : row) : [...current.subscriptions, value] });
  }
  async function save() {
    setInvalidLine(null);
    const value = await task.run('rules', () => toolsApi.saveWebFilters(rules), t('saved'));
    if (value) { setSettings(value); setRules(value.custom_rules); }
  }
  async function add() {
    if (!adding) return;
    const value = await task.run('add', () => toolsApi.addWebSubscription(adding));
    if (value) { replaceSubscription(value); setAdding(null); }
  }
  async function enabled(row: WebSubscription, value: boolean) {
    const updated = await task.run(row.id, () => toolsApi.setWebSubscriptionEnabled(row.id, value));
    if (updated) replaceSubscription(updated);
  }
  async function refresh(row: WebSubscription) {
    const updated = await task.run(row.id, () => toolsApi.refreshWebSubscription(row.id));
    if (updated) replaceSubscription(updated);
  }
  async function remove(row: WebSubscription) {
    const removed = await task.run(row.id, async () => { await toolsApi.deleteWebSubscription(row.id); return true; });
    if (removed) setSettings((current) => current && { ...current, subscriptions: current.subscriptions.filter((item) => item.id !== row.id) });
  }
  return { settings, rules, adding, setAdding, invalidLine, task, save, add, enabled, refresh, remove,
    dirty: !!settings && rules !== settings.custom_rules || !!adding && !!(adding.name || adding.url),
    reload: () => setReload((value) => value + 1),
    changeRules: (value: string) => { setRules(value); setInvalidLine(null); task.setError(''); task.setNotice(''); } };
}

export function WebFiltersSettings({ filters, disabled, confirm }: {
  filters: ReturnType<typeof useWebFilters>; disabled: boolean; confirm: ConfirmAction;
}) {
  const { t, i18n } = useTranslation('settings');
  const { settings, task, adding } = filters;
  const formatDate = (value: string) => new Date(value).toLocaleString(i18n.language);
  function issueText(issue: WebFilterIssue) {
    if (issue.line !== null) return t('webFilters.invalidRule', { line: issue.line });
    if (issue.code === 'WEB_FILTER_ENCODING_INVALID') return t('webFilters.invalidEncoding');
    return t('webFilters.downloadFailed');
  }
  async function closeAdd() {
    if (disabled || adding && (adding.name || adding.url) && !(await confirm(t('resources.discardConfirm')))) return;
    filters.setAdding(null);
  }
  return <>
    <section className="flex min-w-0 flex-col gap-3" aria-labelledby="web-subscriptions-heading">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="web-subscriptions-heading">{t('webFilters.subscriptions')}</h2>
        <Button type="button" variant="outline" disabled={disabled || !settings} onClick={() => {
          task.setError(''); filters.setAdding({ name: '', url: '' });
        }}><Plus data-icon="inline-start" />{t('webFilters.add')}</Button>
      </div>
      <ItemDescription className="line-clamp-none">{t('webFilters.schedule')}{settings?.next_update_at ? ' ' + t('webFilters.nextUpdate', { date: formatDate(settings.next_update_at) }) : ''}</ItemDescription>
      {!adding && filters.invalidLine === null ? <Feedback error={task.error} notice={task.notice} /> : null}
      {settings ? settings.subscriptions.length ? <ItemGroup>
        {settings.subscriptions.map((row) => <Item key={row.id} variant="outline" role="group" aria-label={row.name} className="flex-wrap" data-subscription-id={row.id}>
          <Switch checked={row.enabled} disabled={disabled} aria-label={t('webFilters.enabled', { name: row.name })}
            onCheckedChange={(value) => void filters.enabled(row, value)} />
          <ItemContent className="min-w-0">
            <ItemTitle className="min-w-0"><a className="truncate" href={row.url} title={row.url} target="_blank" rel="noopener noreferrer">{row.name}</a></ItemTitle>
            <ItemDescription className="line-clamp-none">{t('webFilters.ruleCount', { count: row.rule_count })} · {row.last_success_at
              ? t('webFilters.updated', { date: formatDate(row.last_success_at) }) : t('webFilters.notDownloaded')}</ItemDescription>
            {row.error ? <Feedback error={issueText(row.error)} /> : null}
          </ItemContent>
          <ItemActions className="max-sm:ml-auto">
            <Button type="button" variant="ghost" size="icon" disabled={disabled} title={t('webFilters.update', { name: row.name })}
              aria-label={t('webFilters.update', { name: row.name })} onClick={() => void filters.refresh(row)}><RefreshCw data-icon="inline-start" /></Button>
            <Button type="button" variant="ghost" size="icon" disabled={disabled} title={t('webFilters.delete', { name: row.name })}
              aria-label={t('webFilters.delete', { name: row.name })} onClick={() => void (async () => {
                if (await confirm(t('webFilters.deleteConfirm', { name: row.name }), { destructive: true })) await filters.remove(row);
              })()}><Trash2 data-icon="inline-start" /></Button>
          </ItemActions>
        </Item>)}
      </ItemGroup> : <ResourceEmpty>{t('webFilters.empty')}</ResourceEmpty> : task.error
        ? <Button type="button" variant="outline" className="self-start" onClick={filters.reload}>{t('resources.refresh')}</Button> : <LoadingStatus />}
    </section>
    <Separator />
    <section className="flex min-w-0 flex-col gap-3" aria-labelledby="web-custom-rules-heading">
      <h2 id="web-custom-rules-heading">{t('webFilters.custom')}</h2>
      <form className="flex min-w-0 flex-col gap-3" onSubmit={(event) => { event.preventDefault(); void filters.save(); }}>
        <FieldGroup>
          <Field data-invalid={filters.invalidLine !== null || undefined} data-disabled={disabled || !settings}>
            <FieldLabel htmlFor="web-custom-rules" className="sr-only">{t('webFilters.custom')}</FieldLabel>
            <Textarea id="web-custom-rules" rows={10} className="min-h-48 max-h-96 resize-y" spellCheck={false}
              disabled={disabled || !settings} aria-invalid={filters.invalidLine !== null}
              aria-describedby={filters.invalidLine === null ? 'web-rules-syntax' : 'web-rules-syntax web-rules-error'}
              value={filters.rules} onChange={(event) => filters.changeRules(event.target.value)} />
            {filters.invalidLine !== null ? <FieldError id="web-rules-error">{task.error}</FieldError> : null}
            <FieldDescription id="web-rules-syntax">{t('webFilters.syntax')}</FieldDescription>
          </Field>
        </FieldGroup>
        <div className="settings-form-actions"><Button type="submit" disabled={disabled || !settings || filters.rules === settings.custom_rules}>{t('save')}</Button></div>
      </form>
    </section>
    <Dialog open={adding !== null} onOpenChange={(open) => { if (!open) void closeAdd(); }}>
      <DialogContent>
        <DialogHeader><DialogTitle>{t('webFilters.add')}</DialogTitle></DialogHeader>
        <form className="flex min-h-0 flex-col gap-4" onSubmit={(event) => { event.preventDefault(); void filters.add(); }}>
          <div className="min-h-0 overflow-y-auto">
            <Feedback error={task.error} />
            <FieldGroup>
              <Field data-disabled={disabled}>
                <FieldLabel htmlFor="web-subscription-name">{t('webFilters.name')}</FieldLabel>
                <Input id="web-subscription-name" required maxLength={160} disabled={disabled} value={adding?.name ?? ''}
                  onChange={(event) => filters.setAdding((current) => current && { ...current, name: event.target.value })} />
              </Field>
              <Field data-disabled={disabled}>
                <FieldLabel htmlFor="web-subscription-url">{t('webFilters.url')}</FieldLabel>
                <Input id="web-subscription-url" type="url" required maxLength={4096} disabled={disabled} value={adding?.url ?? ''}
                  onChange={(event) => filters.setAdding((current) => current && { ...current, url: event.target.value })} />
              </Field>
            </FieldGroup>
          </div>
          <DialogFooter><Button type="submit" disabled={disabled}>{t('webFilters.add')}</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  </>;
}

