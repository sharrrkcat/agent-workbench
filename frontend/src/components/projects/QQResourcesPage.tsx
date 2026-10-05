import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Heart, ImageOff, RotateCcw, Save, Trash2 } from 'lucide-react';
import { Attachment, AttachmentActions, AttachmentAction, AttachmentContent, AttachmentDescription,
  AttachmentMedia, AttachmentTitle, AttachmentTrigger } from '@/components/ui/attachment';
import { Button } from '@/components/ui/button';
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Pagination, PaginationContent, PaginationItem, PaginationLink, PaginationNext, PaginationPrevious, PaginationEllipsis } from '@/components/ui/pagination';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { SidebarTrigger } from '@/components/ui/sidebar';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { Toggle } from '@/components/ui/toggle';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { qqResourcesApi, type QQResource, type QQResourcePage, type QQResourceQuery } from '../../api/qq';
import { ApiError } from '../../api/http';
import { API_BASE_URL, resolveAttachmentUrlFromBase } from '../../api/url';
import { useProjectsStore } from '../../store/useProjectsStore';
import { useCogitaStore } from '../../store/useCogitaStore';
import { attachmentSize } from '../messages/ChatAttachments';
import { Feedback, ResourceEmpty, ResourceLoading, errorText, type LeaveGuard } from '../settings/resources/ResourceUI';
import type { SettingsNavigate } from '../settings/navigation';
import { readResourceQuery, resourcePages, resourceQueryUrl } from './qqResources';

const filters = ['all', 'favorites', 'unfavorited'] as const;
const sorts = ['created_at:desc', 'created_at:asc', 'size:desc', 'size:asc'] as const;
const imageUrl = (resource: QQResource) => resolveAttachmentUrlFromBase(API_BASE_URL, resource.attachment.uri);

function ResourceImage({ resource, preview = false }: { resource: QQResource; preview?: boolean }) {
  const { t } = useTranslation('personas');
  const [failed, setFailed] = useState(false);
  if (failed) return <span className="flex items-center justify-center gap-2 p-4 text-muted-foreground" role="img" aria-label={t('qq.resources.previewUnavailable')}>
    <ImageOff /><span>{t('qq.resources.previewUnavailable')}</span>
  </span>;
  return <img src={imageUrl(resource)} alt={resource.description || t('image')} loading={preview ? 'eager' : 'lazy'}
    className={preview ? 'max-h-[40vh] w-full object-contain' : undefined} onError={() => setFailed(true)} />;
}

function Favorite({ resource, disabled, onChange }: { resource: QQResource; disabled: boolean; onChange: () => void }) {
  const { t } = useTranslation('personas');
  return <Toggle variant="favorite" pressed={resource.is_favorite} disabled={disabled}
    aria-label={t(resource.is_favorite ? 'qq.resources.unfavorite' : 'qq.resources.favorite')}
    onPressedChange={onChange}><Heart className={resource.is_favorite ? 'fill-current' : undefined} /></Toggle>;
}

export function QQResourcesPage({ projectId, search, onNavigate, onLeaveGuardChange }: {
  projectId: string; search: string; onNavigate: SettingsNavigate; onLeaveGuardChange: (guard: LeaveGuard) => void;
}) {
  const { t, i18n } = useTranslation('personas');
  const { confirm, confirmation } = useConfirmDialog();
  const project = useProjectsStore((state) => state.projects.find((p) => p.id === projectId));
  const projectError = useCogitaStore((state) => state.error);
  const query = useMemo(() => readResourceQuery(search), [search]);
  const queryKey = JSON.stringify(query);
  const [data, setData] = useState<{ key: string; page: QQResourcePage }>();
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<QQResource | null>(null);
  const [draft, setDraft] = useState('');
  const [baseline, setBaseline] = useState('');
  const descriptionId = useId();
  const textarea = useRef<HTMLTextAreaElement>(null);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const live = useRef(true);
  const requestId = useRef(0);
  const dirty = selected !== null && draft !== baseline;
  const status = useRef({ dirty, busy });
  status.current = { dirty, busy };
  const guard = useCallback<LeaveGuard>(async () => {
    if (status.current.busy || (status.current.dirty && !(await confirm(t('discardChanges'))))) return false;
    status.current.dirty = false;
    setSelected(null);
    return true;
  }, [confirm, t]);
  useEffect(() => { onLeaveGuardChange(guard); return () => onLeaveGuardChange(async () => true); }, [guard, onLeaveGuardChange]);
  useEffect(() => {
    live.current = true;
    const unload = (event: BeforeUnloadEvent) => {
      if (status.current.dirty || status.current.busy) { event.preventDefault(); event.returnValue = ''; }
    };
    window.addEventListener('beforeunload', unload);
    return () => { live.current = false; requestId.current++; window.removeEventListener('beforeunload', unload); };
  }, []);
  useEffect(() => {
    if (project?.kind !== 'qqbot') return;
    const id = ++requestId.current;
    setLoading(true); setLoadError('');
    void qqResourcesApi.list(query).then((page) => {
      if (id === requestId.current) setData({ key: queryKey, page });
    }).catch((reason) => { if (id === requestId.current) setLoadError(errorText(reason)); })
      .finally(() => { if (id === requestId.current) setLoading(false); });
    return () => { requestId.current++; };
  }, [project?.kind, query, queryKey, reload]);
  const currentPage = data?.key === queryKey ? data.page : undefined;
  const lastPage = Math.max(1, Math.ceil((currentPage?.total ?? 0) / 30));
  useEffect(() => {
    if (currentPage && !loading && !selected && query.page > lastPage)
      void onNavigate(resourceQueryUrl(projectId, { ...query, page: lastPage }));
  }, [currentPage, loading, selected, query, lastPage, onNavigate, projectId]);

  async function mutate(work: () => Promise<void>) {
    if (status.current.busy) return;
    status.current.busy = true; setBusy(true); requestId.current++; setError(''); setNotice('');
    try { await work(); }
    catch (reason) { if (live.current) setError(errorText(reason)); }
    finally {
      status.current.busy = false;
      if (live.current) { setBusy(false); setReload((n) => n + 1); }
    }
  }
  async function remove(resource: QQResource, orphan = false) {
    if (status.current.busy || !(await confirm(t(orphan ? 'qq.resources.orphanConfirm' : 'qq.resources.deleteConfirm'), { destructive: true }))) return;
    if (!live.current) return;
    await mutate(async () => {
      await qqResourcesApi.remove(resource.id);
      if (live.current) {
        setSelected((value) => value?.id === resource.id ? null : value);
        setData((value) => value ? { ...value, page: { ...value.page, total: Math.max(0, value.page.total - 1),
          items: value.page.items.filter((item) => item.id !== resource.id) } } : value);
        setNotice(t('qq.resources.deleted'));
      }
    });
  }
  async function favorite(resource: QQResource) {
    if (resource.is_favorite && !resource.has_references) { await remove(resource, true); return; }
    let orphan = false;
    await mutate(async () => {
      let updated: QQResource;
      try { updated = await qqResourcesApi.update(resource.id, { is_favorite: !resource.is_favorite }); }
      catch (reason) {
        if (reason instanceof ApiError && reason.code === 'QQ_RESOURCE_UNREFERENCED') { orphan = true; return; }
        throw reason;
      }
      if (live.current) {
        setSelected((value) => value?.id === updated.id ? updated : value);
        setData((value) => value ? { ...value, page: { ...value.page,
          items: value.page.items.map((item) => item.id === updated.id ? updated : item) } } : value);
      }
    });
    if (orphan && live.current) await remove(resource, true);
  }
  async function save() {
    if (!selected) return;
    await mutate(async () => {
      const updated = await qqResourcesApi.update(selected.id, { description: draft });
      if (live.current) {
        setSelected(updated); setDraft(updated.description || ''); setBaseline(updated.description || '');
        status.current.dirty = false; setNotice(t('qq.resources.saved'));
      }
    });
  }
  const navigateQuery = (values: Partial<QQResourceQuery>) => onNavigate(resourceQueryUrl(projectId, { ...query, ...values }));
  const metadata = (resource: QQResource) => `${resource.attachment.mime_type.split('/')[1].toUpperCase()} · ${attachmentSize(resource.attachment.size, i18n.language)}`;
  return <>
    <header className="settings-header"><SidebarTrigger /><div className="settings-heading min-w-0"><h1>{t('qq.resources.title')}</h1></div></header>
    <div className="settings-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain">
      <div className="qq-resources-content flex flex-col gap-4">
        {!project ? <ResourceLoading error={projectError || undefined} retry={() => void useCogitaStore.getState().activateLocation(projectId)} /> :
          project.kind !== 'qqbot' ? <ResourceEmpty>{t('qq.resources.qqOnly')}</ResourceEmpty> : <>
            {!selected ? <Feedback error={error || (currentPage ? loadError : '')} notice={notice} /> : null}
            <Tabs value={query.favorite} onValueChange={(value) => void navigateQuery({ favorite: value as QQResourceQuery['favorite'], page: 1 })}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <TabsList aria-label={t('qq.resources.filter')}>
                    {filters.map((value) => <TabsTrigger key={value} value={value} disabled={busy}>{t('qq.resources.' + value)}</TabsTrigger>)}
                  </TabsList>
                  {currentPage ? <p className="whitespace-nowrap text-muted-foreground" role="status">{t('qq.resources.count', { count: currentPage.total })}</p> : null}
                </div>
                <Select value={`${query.sort}:${query.order}`} disabled={busy} onValueChange={(value) => {
                  if (!value) return;
                  const [sort, order] = value.split(':');
                  void navigateQuery({ sort: sort as QQResourceQuery['sort'], order: order as QQResourceQuery['order'], page: 1 });
                }}>
                  <SelectTrigger className="w-auto min-w-40" aria-label={t('qq.resources.sort')}><SelectValue>
                    {t('qq.resources.sortOptions.' + query.sort + '_' + query.order)}
                  </SelectValue></SelectTrigger>
                  <SelectContent><SelectGroup>{sorts.map((value) => <SelectItem key={value} value={value}>
                    {t('qq.resources.sortOptions.' + value.replace(':', '_'))}
                  </SelectItem>)}</SelectGroup></SelectContent>
                </Select>
              </div>
              <TabsContent value={query.favorite} className="flex flex-col gap-4" aria-busy={loading}>
                {!currentPage ? <ResourceLoading error={loadError} retry={() => setReload((n) => n + 1)} /> : <>
                  {!currentPage.items.length ? <ResourceEmpty>{t('qq.resources.empty')}</ResourceEmpty> :
                    <div className="qq-resource-grid">
                      {currentPage.items.map((resource) => <Attachment key={resource.id} orientation="vertical" className="w-full" data-resource-id={resource.id}>
                        <AttachmentMedia variant="image"><ResourceImage resource={resource} /></AttachmentMedia>
                        <AttachmentContent><AttachmentTitle className="line-clamp-2 min-h-8 whitespace-normal" title={resource.description || undefined}>
                          {resource.description || t('qq.resources.noDescription')}
                        </AttachmentTitle><AttachmentDescription>{metadata(resource)}</AttachmentDescription></AttachmentContent>
                        <AttachmentTrigger disabled={busy} aria-label={t('qq.resources.edit', { name: resource.description || t('qq.resources.noDescription') })}
                          onClick={(event) => { trigger.current = event.currentTarget; setSelected(resource); setDraft(resource.description || '');
                            setBaseline(resource.description || ''); setNotice(''); setError(''); }} />
                        <AttachmentActions className="top-2! right-2! opacity-0 transition-opacity duration-180 group-hover/attachment:opacity-100 group-focus-within/attachment:opacity-100 pointer-coarse:opacity-100 motion-reduce:transition-none">
                          <Favorite resource={resource} disabled={busy} onChange={() => void favorite(resource)} />
                          <AttachmentAction variant="secondary" size="icon" disabled={busy} aria-label={t('qq.resources.delete')}
                            onClick={() => void remove(resource)}><Trash2 /></AttachmentAction>
                        </AttachmentActions>
                      </Attachment>)}
                    </div>}
                  <Pagination>
                    <PaginationContent>
                      <PaginationItem><PaginationPrevious href={resourceQueryUrl(projectId, { ...query, page: Math.max(1, query.page - 1) })}
                        aria-disabled={busy || query.page <= 1} tabIndex={busy || query.page <= 1 ? -1 : 0}
                        onClick={(event) => { event.preventDefault(); if (!busy && query.page > 1) void navigateQuery({ page: query.page - 1 }); }} /></PaginationItem>
                      {resourcePages(query.page, lastPage).map((value, index) => <PaginationItem key={`${value}-${index}`}>
                        {value === 'ellipsis' ? <PaginationEllipsis /> : <PaginationLink isActive={value === query.page}
                          href={resourceQueryUrl(projectId, { ...query, page: value })} aria-label={t('qq.resources.page', { page: value })}
                          aria-disabled={busy} onClick={(event) => { event.preventDefault(); if (!busy) void navigateQuery({ page: value }); }}>{value}</PaginationLink>}
                      </PaginationItem>)}
                      <PaginationItem><PaginationNext href={resourceQueryUrl(projectId, { ...query, page: Math.min(lastPage, query.page + 1) })}
                        aria-disabled={busy || query.page >= lastPage} tabIndex={busy || query.page >= lastPage ? -1 : 0}
                        onClick={(event) => { event.preventDefault(); if (!busy && query.page < lastPage) void navigateQuery({ page: query.page + 1 }); }} /></PaginationItem>
                    </PaginationContent>
                  </Pagination>
                </>}
              </TabsContent>
            </Tabs>
          </>}
      </div>
    </div>
    <Sheet open={selected !== null} onOpenChange={(open) => { if (!open) void guard(new URL(window.location.href)).then((allowed) => { if (allowed && live.current) setSelected(null); }); }}>
      <SheetContent className="w-full! sm:max-w-[30rem]!" initialFocus={textarea} finalFocus={trigger}>
        <SheetHeader><SheetTitle>{t('qq.resources.details')}</SheetTitle><SheetDescription>{t('qq.resources.editHint')}</SheetDescription></SheetHeader>
        {selected ? <>
          <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overscroll-contain px-6 pb-4">
            <ResourceImage key={selected.id} resource={selected} preview />
            <p className="text-muted-foreground">{metadata(selected)} · {t('qq.resources.added', { date: new Date(selected.created_at.match(/Z$|[+-]\d\d:\d\d$/) ? selected.created_at : selected.created_at + 'Z').toLocaleString(i18n.language) })}</p>
            <FieldGroup><Field><FieldLabel htmlFor={descriptionId}>{t('qq.resources.description')}</FieldLabel>
              <Textarea ref={textarea} id={descriptionId} value={draft} rows={5} disabled={busy} onChange={(event) => setDraft(event.target.value)} />
            </Field></FieldGroup>
            <Feedback error={error} notice={notice} />
          </div>
          <SheetFooter>
            <div className="flex flex-wrap items-center gap-2">
              <Favorite resource={selected} disabled={busy} onChange={() => void favorite(selected)} />
              <Button variant="outline" disabled={!dirty || busy} onClick={() => { setDraft(baseline); setNotice(''); }}><RotateCcw data-icon="inline-start" />{t('qq.resources.reset')}</Button>
              <Button variant="destructive" disabled={busy} onClick={() => void remove(selected)}><Trash2 data-icon="inline-start" />{t('qq.resources.delete')}</Button>
              <Button className="ml-auto" disabled={!dirty || busy} onClick={() => void save()}><Save data-icon="inline-start" />{t('save')}</Button>
            </div>
          </SheetFooter>
        </> : null}
        {selected ? confirmation : null}
      </SheetContent>
    </Sheet>
    {!selected ? confirmation : null}
  </>;
}
