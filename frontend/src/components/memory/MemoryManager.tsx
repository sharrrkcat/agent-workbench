import { useEffect, useId, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { Plus, Search, ChevronDown, Pencil, Trash2, Share2, Pin, Info, MoreHorizontal } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from '@/components/ui/input-group';
import { Card, CardContent, CardFooter, CardHeader } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Badge } from '@/components/ui/badge';
import { Field, FieldLabel } from '@/components/ui/field';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { memoriesApi } from '../../api/memories';
import { chatApi } from '../../api/chat';
import { charactersApi } from '../../api/characters';
import { ApiError } from '../../api/http';
import { useCharactersStore } from '../../store/useCharactersStore';
import { usePersonasStore } from '../../store/usePersonasStore';
import { COGITA_CHARACTER_ID, USER_PERSONA_ID, type NormalSession, type Session } from '../../types/chat';
import type { MemoryCreate, MemoryEntry, MemoryPage, MemoryPreview, MemoryQuery } from '../../types/memory';
import { Feedback, ResourceEmpty, ResourceLoading, errorText } from '../settings/resources/ResourceUI';
import { MemoryEditor } from './MemoryEditor';
import { MemorySelect } from './MemoryFields';

export function MemoryManager({ characterId, session, addButtonContainer }: {
  characterId?: string; session?: NormalSession; addButtonContainer?: HTMLElement | null;
}) {
  const { t } = useTranslation('memory'); const id = useId();
  const [scope, setScope] = useState('own');
  const [filters, setFilters] = useState<MemoryQuery>({ character_id: characterId, pool: characterId ? 'character' : undefined });
  const [query, setQuery] = useState(''); const [search, setSearch] = useState(''); const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<MemoryPage | null>(null); const [error, setError] = useState('');
  const [reload, setReload] = useState(0); const [loading, setLoading] = useState(true);
  const [editor, setEditor] = useState<MemoryCreate | null>(null);
  const [sourceSessions, setSourceSessions] = useState<Session[]>([]);
  const characters = useCharactersStore((s) => s.characters).filter((c) => c.kind === 'normal');
  const personas = usePersonasStore((s) => s.personas);
  const sessionOwners = session ? '' : characters.map((c) => c.id).sort().join(',');
  useEffect(() => {
    if (!sessionOwners) return;
    let active = true;
    void Promise.all(sessionOwners.split(',').map((owner) => charactersApi.listSessions(owner)))
      .then((values) => { if (active) setSourceSessions(values.flat()); })
      .catch((reason) => { if (active) setError(errorText(reason)); });
    return () => { active = false; };
  }, [sessionOwners]);
  useEffect(() => {
    let active = true;
    void Promise.all([useCharactersStore.getState().reload(), usePersonasStore.getState().reload()])
      .catch((reason) => { if (active) setError(errorText(reason)); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError('');
    const read = session ? scope === 'own'
      ? memoriesApi.list({ session_id: session.session_id, q: search, offset }, controller.signal)
      : memoriesApi.session(session.session_id, { q: search, offset }, controller.signal)
      : memoriesApi.list({ ...filters, q: search, offset }, controller.signal);
    void read.then((value) => { if (!controller.signal.aborted) setPage(value); })
      .catch((reason) => { if (!controller.signal.aborted) setError(errorText(reason)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [session?.session_id, session?.memory_version, filters, search, offset, scope, reload]);
  function change(values: MemoryQuery) {
    if (Object.entries(values).every(([key, value]) => filters[key as keyof MemoryQuery] === value)) return;
    setFilters((current) => ({ ...current, ...values })); setOffset(0);
  }
  const add = () => setEditor({ pool: filters.pool ?? 'character', character_id: session?.character_id ?? characterId ?? filters.character_id ?? COGITA_CHARACTER_ID,
    persona_id: session?.bound_persona_id ?? filters.persona_id ?? USER_PERSONA_ID, session_id: session?.session_id ?? null, summary: '', body: '', pinned: false });
  const addButton = <Button type="button" variant="outline" onClick={add} disabled={!!session && !session.bound_persona_id}><Plus data-icon="inline-start" />{t('add')}</Button>;
  return <div className="flex min-w-0 flex-col gap-4" data-memory-manager>
    {session || addButtonContainer === undefined ? <div className="flex flex-wrap items-center justify-between gap-3">
      {session ? <ToggleGroup variant="outline" value={[scope]} onValueChange={(next) => { if (next[0]) { setScope(next[0]); setOffset(0); } }} aria-label={t('title')}>
        <ToggleGroupItem value="own">{t('own')}</ToggleGroupItem><ToggleGroupItem value="readable">{t('readable')}</ToggleGroupItem>
      </ToggleGroup> : null}
      {addButtonContainer === undefined ? addButton : null}
    </div> : null}
    {addButtonContainer ? createPortal(addButton, addButtonContainer) : null}
    <div className="memory-toolbar">
      <Field className="memory-search"><FieldLabel htmlFor={id + '-search'} className="sr-only">{t('search')}</FieldLabel>
        <InputGroup><InputGroupInput id={id + '-search'} value={query} maxLength={4000} placeholder={t('search')} onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Enter' && !event.nativeEvent.isComposing) { event.preventDefault(); setSearch(query); setOffset(0); } }} />
          <InputGroupAddon align="inline-end"><InputGroupButton aria-label={t('searchAction')} title={t('searchAction')} size="icon-xs"
            onClick={() => { setSearch(query); setOffset(0); }}><Search /></InputGroupButton></InputGroupAddon>
        </InputGroup>
      </Field>
      {!session ? <>
      {!characterId ? <MemorySelect compact label={t('character')} value={filters.character_id ?? ''}
        options={[{ value: '', label: t('all') }, ...characters.map((c) => ({ value: c.id, label: c.name }))]}
        onChange={(value) => change({ character_id: value || undefined, session_id: undefined })} /> : null}
      <MemorySelect compact label={t('persona')} value={filters.persona_id ?? ''} options={[{ value: '', label: t('all') }, ...personas.map((p) => ({ value: p.id, label: p.name }))]}
        onChange={(value) => change({ persona_id: value || undefined })} />
      <MemorySelect compact label={t('pool')} value={filters.pool ?? ''} options={[{ value: '', label: t('all') }, { value: 'character', label: t('characterPool') }, { value: 'general', label: t('general') }]}
        onChange={(value) => change({ pool: value as MemoryQuery['pool'] || undefined })} />
      <MemorySelect compact label={t('session')} value={filters.origin_session_id ?? ''}
        options={[{ value: '', label: t('all') }, ...sourceSessions.map((source) => ({ value: source.session_id, label: source.title || t('personas:newSession') }))]}
        onChange={(value) => change({ origin_session_id: value || undefined })} />
      </> : null}
    </div>
    <Feedback error={error} />
    <div className="memory-results" aria-busy={loading}>
    {!page && loading ? <ResourceLoading /> : page?.items.length ? <div className="flex flex-col gap-2">
      {page.items.map((entry) => <MemoryRow key={`${entry.id}:${entry.revision}:${scope}`} entry={entry} sessionId={scope === 'readable' ? session?.session_id : undefined}
        editable={!session || scope === 'own'} onChanged={() => setReload((v) => v + 1)} />)}
    </div> : !error ? <ResourceEmpty>{t('empty')}</ResourceEmpty> : null}
    </div>
    {page ? <div className="flex flex-wrap items-center justify-between gap-2"><span className="settings-note">{t('pageCount', { count: page.total })}</span>
      <div className="flex gap-2"><Button type="button" variant="outline" disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>{t('previous')}</Button>
        <Button type="button" variant="outline" disabled={loading || page.next_offset === null} onClick={() => setOffset(page.next_offset ?? 0)}>{t('next')}</Button></div>
    </div> : null}
    {editor ? <MemoryEditor initial={editor} onClose={() => setEditor(null)} onSaved={() => setReload((v) => v + 1)} /> : null}
  </div>;
}

function MemoryRow({ entry, sessionId, editable, onChanged }: { entry: MemoryPreview; sessionId?: string; editable: boolean; onChanged: () => void }) {
  const { t } = useTranslation('memory'); const { confirm, confirmation } = useConfirmDialog();
  const [open, setOpen] = useState(false); const [full, setFull] = useState<MemoryEntry | null>(null);
  const [editing, setEditing] = useState(false); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const [sourceSession, setSourceSession] = useState<string | null>(null); const [sourceOpen, setSourceOpen] = useState(false);
  const characters = useCharactersStore((s) => s.characters); const personas = usePersonasStore((s) => s.personas);
  const persona = personas.find((p) => p.id === entry.persona_id)?.name ?? t('deletedSource');
  useEffect(() => {
    if (!open || full) return;
    const controller = new AbortController();
    void (sessionId ? memoriesApi.sessionEntry(sessionId, entry.id, controller.signal) : memoriesApi.get(entry.id, controller.signal))
      .then((value) => { if (!controller.signal.aborted) setFull(value); })
      .catch((reason) => { if (!controller.signal.aborted) setError(errorText(reason)); });
    return () => controller.abort();
  }, [open, entry.id, sessionId, full]);
  useEffect(() => {
    if (!sourceOpen || !full?.origin.session_id) return;
    const controller = new AbortController();
    void chatApi.getSession(full.origin.session_id, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setSourceSession(value.title || t('personas:newSession')); })
      .catch((reason) => {
        if (controller.signal.aborted) return;
        if (reason instanceof ApiError && reason.code === 'SESSION_NOT_FOUND') setSourceSession(t('deletedSource'));
        else setError(errorText(reason));
      });
    return () => controller.abort();
  }, [sourceOpen, full?.origin.session_id, t]);
  async function action(kind: 'forget' | 'publish') {
    if (!(await confirm(kind === 'forget' ? t('forgetConfirm') : t('publishConfirm', { persona }), { destructive: kind === 'forget' }))) return;
    setBusy(true); setError('');
    try { await (kind === 'forget' ? memoriesApi.forget(entry.id, entry.revision) : memoriesApi.publish(entry.id, entry.revision)); onChanged(); }
    catch (reason) { setError(errorText(reason)); }
    finally { setBusy(false); }
  }
  return <Collapsible open={open} onOpenChange={setOpen} data-memory-id={entry.id}>
    <Card size="sm" className="gap-0 p-0">
      <CardHeader className="p-0">
        <CollapsibleTrigger render={<Button type="button" variant="ghost" aria-label={entry.summary} className="h-auto w-full justify-between whitespace-normal p-3 text-left" />}>
          <span className="min-w-0 break-words">{entry.summary}</span>
          <span className="flex shrink-0 items-center gap-2">
            <Badge variant="secondary" className="max-w-28 truncate" title={persona}>{persona}</Badge>
            {entry.pinned ? <Pin /> : null}
            <ChevronDown className={open ? 'rotate-180' : undefined} />
          </span>
        </CollapsibleTrigger>
      </CardHeader>
      <CollapsibleContent>
        <CardContent className="flex flex-col gap-3 py-3">
          <Feedback error={error} />
          {full ? <p className="whitespace-pre-wrap break-words">{full.body}</p> : !error ? <ResourceLoading /> : null}
        </CardContent>
        {full ? <CardFooter className="justify-end gap-1 pb-3">
          <Dialog open={sourceOpen} onOpenChange={setSourceOpen}>
            <DialogTrigger render={<Button type="button" variant="ghost" size="icon" aria-label={t('origin')} title={t('origin')} />}><Info /></DialogTrigger>
            <DialogContent><DialogHeader><DialogTitle>{t('origin')}</DialogTitle></DialogHeader>
              <div className="flex min-w-0 flex-col gap-3">
                <div className="flex flex-wrap gap-2"><Badge variant="outline">{t(entry.pool === 'general' ? 'general' : 'characterPool')}</Badge><Badge variant="outline">{t('version', { revision: entry.revision })}</Badge></div>
                <p className="settings-note break-words">
                  {characters.find((c) => c.id === full.origin.character_id)?.name ?? t('deletedSource')} · {persona} · {new Date(full.observed_at).toLocaleDateString()}
                </p>
                {full.origin.session_id ? <p className="settings-note break-all">{t('sourceSession', { name: sourceSession ?? '…', id: full.origin.session_id })}</p> : null}
                {full.origin.run_id ? <p className="settings-note break-all">{t('sourceRun', { id: full.origin.run_id })}</p> : null}
                {full.origin.evidence.length ? full.origin.evidence.map((e) => <p className="settings-note break-all" key={e.message_id}>{t('sourceMessage', { id: e.message_id })}</p>) : <p className="settings-note">{t('manualSource')}</p>}
              </div>
            </DialogContent>
          </Dialog>
          {editable ? <DropdownMenu>
            <DropdownMenuTrigger render={<Button type="button" variant="ghost" size="icon" disabled={busy} aria-label={t('actions')} title={t('actions')} />}><MoreHorizontal /></DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-auto"><DropdownMenuGroup>
              <DropdownMenuItem onClick={() => setEditing(true)}><Pencil />{t('edit')}</DropdownMenuItem>
              <DropdownMenuItem disabled={entry.pool !== 'character'} onClick={() => void action('publish')}><Share2 />{t('publish')}</DropdownMenuItem>
              <DropdownMenuItem variant="destructive" onClick={() => void action('forget')}><Trash2 />{t('delete')}</DropdownMenuItem>
            </DropdownMenuGroup></DropdownMenuContent>
          </DropdownMenu> : null}
        </CardFooter> : null}
      </CollapsibleContent>
    </Card>
    {editing && full ? <MemoryEditor entry={full} initial={{ pool: full.pool, character_id: full.character_id, persona_id: full.persona_id,
      session_id: full.session_id, summary: full.summary, body: full.body, pinned: full.pinned }} onClose={() => setEditing(false)} onSaved={onChanged} /> : null}
    {confirmation}
  </Collapsible>;
}
