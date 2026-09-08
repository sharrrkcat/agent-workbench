import { useEffect, useRef, useState } from 'react';
import { Plus } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { WorldbookEntry, WorldbookEntryInput } from '../../../types/worldbook';
import { worldbookApi } from '../../../api/worldbook';
import { equalDraft, errorText, ResourceLoading } from '../resources/ResourceUI';
import { WorldbookEntryCard } from './WorldbookEntryCard';

export const entryInput = (entry?: WorldbookEntryInput): WorldbookEntryInput => ({
  name: entry?.name ?? '', keywords_text: entry?.keywords_text ?? '', content: entry?.content ?? '',
  activation_mode: entry?.activation_mode ?? 'keyword', enabled: entry?.enabled ?? true,
});

export function WorldbookEntries({ bookId, onState, onCount }: {
  bookId: string; onState: (state: { dirty: boolean; busy: boolean }) => void; onCount: (count: number) => void;
}) {
  const { t } = useTranslation('worldbook');
  const [entries, setEntries] = useState<WorldbookEntry[]>([]);
  const [drafts, setDrafts] = useState<Record<string, WorldbookEntryInput>>({});
  const [expanded, setExpanded] = useState<string[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState('');
  const [dragging, setDragging] = useState('');
  const [notice, setNotice] = useState('');
  const lock = useRef(false);
  const drag = useRef<{ id: string; target: string } | null>(null);
  const dirty = Object.entries(drafts).some(([id, draft]) => id === 'new' || !equalDraft(draft, entryInput(entries.find((entry) => entry.id === id))));
  useEffect(() => { onState({ dirty, busy: !!busy || loading || !!dragging }); }, [dirty, busy, loading, dragging, onState]);
  useEffect(() => {
    let live = true;
    setLoading(true); setLoadError('');
    void worldbookApi.listWorldbookEntries(bookId).then((values) => { if (live) { setEntries(values); setLoading(false); } })
      .catch((reason) => { if (live) { setLoadError(errorText(reason)); setLoading(false); } });
    return () => { live = false; };
  }, [bookId, revision]);

  function update(id: string, patch: Partial<WorldbookEntryInput>) {
    setDrafts((current) => ({ ...current, [id]: { ...(current[id] || entryInput(entries.find((entry) => entry.id === id))), ...patch } }));
  }
  function clearDraft(id: string) {
    setDrafts((current) => { const result = { ...current }; delete result[id]; return result; });
    setErrors((current) => ({ ...current, [id]: '' }));
    if (id === 'new') setExpanded((current) => current.filter((entryId) => entryId !== id));
  }
  async function mutate(id: string, operation: string, action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(`${operation}:${id}`); setErrors((current) => ({ ...current, [id]: '' })); setNotice('');
    try { await action(); } catch (reason) { setErrors((current) => ({ ...current, [id]: errorText(reason) })); }
    finally { lock.current = false; setBusy(''); }
  }
  async function save(id: string) {
    const input = drafts[id] || entryInput(entries.find((entry) => entry.id === id));
    await mutate(id, 'save', async () => {
      const saved = id === 'new' ? await worldbookApi.createWorldbookEntry(bookId, input) : await worldbookApi.patchWorldbookEntry(id, input);
      setEntries((current) => id === 'new' ? [...current, saved] : current.map((item) => item.id === id ? saved : item));
      clearDraft(id); setExpanded((current) => [...new Set([...current.filter((value) => value !== 'new'), saved.id])]);
      onCount(entries.length + (id === 'new' ? 1 : 0)); setNotice(t('entrySaved'));
    });
  }
  async function enable(entry: WorldbookEntry, enabled: boolean) {
    await mutate(entry.id, 'toggle', async () => {
      setEntries((current) => current.map((item) => item.id === entry.id ? { ...item, enabled } : item));
      update(entry.id, { enabled });
      try {
        const saved = await worldbookApi.patchWorldbookEntry(entry.id, { enabled });
        setEntries((current) => current.map((item) => item.id === entry.id ? saved : item));
        update(entry.id, { enabled: saved.enabled });
      } catch (reason) {
        setEntries((current) => current.map((item) => item.id === entry.id ? { ...item, enabled: entry.enabled } : item));
        update(entry.id, { enabled: entry.enabled }); throw reason;
      }
    });
  }
  function remove(id: string) {
    if (id === 'new') { clearDraft(id); return; }
    if (!window.confirm(t('deleteEntryConfirm'))) return;
    void mutate(id, 'delete', async () => {
      await worldbookApi.deleteWorldbookEntry(id);
      setEntries((current) => current.filter((item) => item.id !== id)); clearDraft(id);
      onCount(entries.length - 1); setNotice(t('entryDeleted'));
    });
  }
  async function reorder(id: string, target: string) {
    if (id === target) return;
    const from = entries.findIndex((item) => item.id === id), to = entries.findIndex((item) => item.id === target);
    if (from < 0 || to < 0) return;
    const next = [...entries]; next.splice(to, 0, next.splice(from, 1)[0]);
    await mutate(id, 'reorder', async () => {
      setEntries(next);
      try { setEntries((await worldbookApi.reorderWorldbookEntries(bookId, next.map((item) => item.id))).entries); setNotice(t('reordered')); }
      catch (reason) { setEntries(entries); throw reason; }
    });
  }
  if (loading || loadError) return <ResourceLoading error={loadError} retry={() => setRevision((value) => value + 1)} />;
  const ids = [...(drafts.new ? ['new'] : []), ...entries.map((entry) => entry.id)];
  return <div className="worldbook-entries">
    <div className="resource-toolbar"><h3>{t('entries')} <span className="resource-count">{entries.length}</span></h3>
      <button type="button" className="secondary-button" disabled={!!busy || !!drafts.new} onClick={() => { update('new', entryInput()); setExpanded((current) => ['new', ...current]); }}><Plus size={16} />{t('newEntry')}</button></div>
    <div role="status" className="resource-notice">{notice}</div>
    <div className="worldbook-entry-card-list">{ids.map((id) => {
      const entry = entries.find((item) => item.id === id);
      const draft = drafts[id] || entryInput(entry);
      return <WorldbookEntryCard key={id} id={id} draft={draft} expanded={expanded.includes(id)} dirty={id === 'new' || !equalDraft(draft, entryInput(entry))}
        busy={busy.endsWith(`:${id}`) ? busy.split(':')[0] : ''} locked={!!busy} dragging={dragging === id} error={errors[id]}
        onToggle={() => setExpanded((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id])}
        onUpdate={(patch) => update(id, patch)} onEnabled={(enabled) => entry ? void enable(entry, enabled) : update(id, { enabled })}
        onSave={() => void save(id)} onReset={() => clearDraft(id)} onDelete={() => remove(id)}
        onPointerDown={(event) => { if (event.button !== 0) return; event.stopPropagation(); event.currentTarget.setPointerCapture(event.pointerId); drag.current = { id, target: id }; setDragging(id); }}
        onPointerMove={(event) => { if (drag.current?.id !== id) return; const target = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>('[data-entry-id]')?.dataset.entryId; if (target && target !== 'new') drag.current.target = target; }}
        onPointerUp={(event) => { const active = drag.current; drag.current = null; setDragging(''); if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); if (active) void reorder(active.id, active.target); }}
        onPointerCancel={() => { drag.current = null; setDragging(''); }}
        onKeyDown={(event) => { if (!['ArrowUp', 'ArrowDown'].includes(event.key)) return; event.preventDefault(); const index = entries.findIndex((item) => item.id === id); const target = entries[index + (event.key === 'ArrowUp' ? -1 : 1)]; if (target) void reorder(id, target.id); }} />;
    })}</div>
    {!ids.length ? <p className="resource-empty">{t('noEntries')}</p> : null}
  </div>;
}
