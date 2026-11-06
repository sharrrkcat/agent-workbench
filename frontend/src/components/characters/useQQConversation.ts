import { useEffect, useRef, useState } from 'react';
import { qqApi, type QQHistoryPage, type QQDeleteTarget } from '../../api/qq';
import { toolsApi } from '../../api/tools';
import type { ToolRunResponse } from '../../types/tools';
import type { HistoryQuery } from '../../types/history';
import { compareTime, terminal } from '../../store/cogita/mergeState';
import { useCogitaStore } from '../../store/useCogitaStore';
import { errorText } from '../settings/resources/ResourceUI';
import { mergeQQHistory, pruneQQHistory, QQHistoryChanged, type QQHistoryDirection } from './qqConversation';

type Detail = { data?: ToolRunResponse; loading: boolean; error: string };

export function useQQConversation(sessionId: string) {
  const [page, setPage] = useState<QQHistoryPage | null>(null);
  const [details, setDetails] = useState<Record<string, Detail>>({});
  const [error, setError] = useState('');
  const [historyLoading, setHistoryLoading] = useState(false);
  const [paging, setPaging] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const refreshVersion = useCogitaStore((state) => state.qqRefreshVersion);
  const current = useRef(page);
  const detailCache = useRef(details);
  const detailRequests = useRef(new Map<string, AbortController>());
  const expanded = useRef(new Set<string>());
  const live = useRef(false);
  const pending = useRef<Promise<void> | null>(null);
  const request = useRef<AbortController | null>(null);
  const explicit = useRef(false);
  const mutating = useRef(false);
  const mutationError = useRef('');
  const revision = useRef(0);
  const following = useRef(true);
  const anchor = useRef<string | null>(null);

  function publishDetails(next: Record<string, Detail>) {
    detailCache.current = next;
    if (live.current) setDetails(next);
  }
  function publish(next: QQHistoryPage) {
    const changed = current.current?.history_version !== next.history_version;
    const runs = new Map(next.items.flatMap((item) => item.kind === 'reply' ? [[item.run.run_id, item.run] as const] : []));
    const kept = Object.fromEntries(Object.entries(detailCache.current).filter(([id, detail]) => {
      const run = runs.get(id);
      return run && !changed && (!detail.data || detail.data.run.updated_at === run.updated_at || !terminal(run.status));
    }));
    for (const [id, controller] of detailRequests.current) if (!runs.has(id) || changed) controller.abort();
    current.current = next; setPage(next); publishDetails(kept);
  }

  async function loadDetail(id: string, force = false) {
    const snapshot = current.current;
    const item = snapshot?.items.find((row) => row.kind === 'reply' && row.run.run_id === id);
    if (!live.current || !snapshot || !item || mutating.current || detailRequests.current.has(id)) return;
    if (!force && detailCache.current[id]?.data) return;
    const epoch = revision.current;
    const controller = new AbortController();
    detailRequests.current.set(id, controller);
    publishDetails({ ...detailCache.current, [id]: { ...detailCache.current[id], loading: true, error: '' } });
    try {
      const value = await toolsApi.getToolRun(id, controller.signal);
      const latest = current.current?.items.find((row) => row.kind === 'reply' && row.run.run_id === id);
      if (controller.signal.aborted || !live.current || epoch !== revision.current || current.current?.history_version !== snapshot.history_version
          || latest?.kind !== 'reply' || compareTime(value.run.updated_at, latest.run.updated_at) < 0) return;
      publishDetails({ ...detailCache.current, [id]: { data: value, loading: false, error: '' } });
    } catch (reason) {
      if (!controller.signal.aborted && live.current && epoch === revision.current)
        publishDetails({ ...detailCache.current, [id]: { ...detailCache.current[id], loading: false, error: errorText(reason) } });
    } finally {
      if (detailRequests.current.get(id) === controller) {
        detailRequests.current.delete(id);
        if (live.current && detailCache.current[id]?.loading)
          publishDetails({ ...detailCache.current, [id]: { ...detailCache.current[id], loading: false } });
      }
    }
  }

  async function refresh(mode: QQHistoryDirection | 'poll' = 'poll') {
    if (!live.current || mutating.current || explicit.current || (mode === 'poll' && pending.current)) return;
    const epoch = revision.current;
    if (mode !== 'poll') {
      explicit.current = true;
      request.current?.abort();
      await pending.current;
      explicit.current = false;
      if (!live.current || epoch !== revision.current) return;
    }
    const saved = current.current;
    const position = mode === 'before' ? saved?.before_cursor : mode === 'after' ? saved?.after_cursor : anchor.current;
    if ((mode === 'before' || mode === 'after') && !position) return;
    if (mode === 'before' || mode === 'after') following.current = false;
    if (mode === 'latest') following.current = true;
    let complete!: () => void;
    pending.current = new Promise<void>((resolve) => { complete = resolve; });
    const controller = new AbortController(); request.current = controller;
    setHistoryLoading(true);
    setPaging(mode !== 'poll');
    try {
      let direction: QQHistoryDirection = mode === 'poll' ? (!following.current && position ? 'around' : 'latest') : mode;
      const windowPoll = mode === 'poll' && direction === 'around' && saved?.items.length;
      const query: HistoryQuery = windowPoll ? { around: saved!.items[0].cursor, limit: 1 } : direction === 'latest'
        ? { limit: mode === 'poll' ? Math.min(100, Math.max(50, saved?.items.length || 0)) : 50 }
        : { [direction]: position!, limit: direction === 'around' ? 100 : 50 };
      let value = await qqApi.history(sessionId, query, controller.signal);
      if (controller.signal.aborted || !live.current || epoch !== revision.current) return;
      if (windowPoll && value.history_version === saved!.history_version) {
        while (value.has_after && value.items.length < saved!.items.length) {
          const next = await qqApi.history(sessionId, { after: value.after_cursor!, limit: Math.min(100, saved!.items.length - value.items.length) }, controller.signal);
          if (controller.signal.aborted || !live.current || epoch !== revision.current) return;
          if (next.history_version !== value.history_version) { value = next; break; }
          value = mergeQQHistory(value, next, 'after');
          if (!next.items.length) break;
        }
      }
      if ((windowPoll || direction === 'before' || direction === 'after') && saved && value.history_version !== saved.history_version) {
        value = await qqApi.history(sessionId, { around: anchor.current ?? position!, limit: 100 }, controller.signal);
        direction = 'around';
      } else if (direction === 'latest' && mode === 'poll' && (saved?.items.length ?? 0) > 100 && value.has_before) {
        const older = await qqApi.history(sessionId, { before: value.before_cursor!, limit: Math.min(100, saved!.items.length - 100) }, controller.signal);
        if (older.history_version !== value.history_version) throw new QQHistoryChanged();
        value = mergeQQHistory(older, value, 'after');
      }
      if (controller.signal.aborted || !live.current || epoch !== revision.current) return;
      publish(mergeQQHistory(saved, value, direction)); setError(mutationError.current);
      for (const id of expanded.current) {
        const row = current.current?.items.find((item) => item.kind === 'reply' && item.run.run_id === id);
        if (row?.kind === 'reply' && !detailCache.current[id]?.error)
          void loadDetail(id, !terminal(row.run.status));
      }
      return true;
    } catch (reason) {
      if (!controller.signal.aborted && live.current && epoch === revision.current && !(reason instanceof QQHistoryChanged)) setError(errorText(reason));
    } finally {
      pending.current = null; complete();
      if (request.current === controller) request.current = null;
      if (live.current) { setHistoryLoading(false); setPaging(false); }
    }
  }

  useEffect(() => {
    live.current = true;
    void refresh();
    const timer = setInterval(() => void refresh(), 1500);
    return () => {
      live.current = false; revision.current++; clearInterval(timer); request.current?.abort();
      for (const controller of detailRequests.current.values()) controller.abort();
    };
  }, [sessionId]);
  useEffect(() => { if (current.current) void refresh(); }, [refreshVersion]);

  async function mutate(action: () => Promise<void>, kind: 'control' | 'delete') {
    if (mutating.current) return;
    mutating.current = true; mutationError.current = ''; revision.current++;
    const epoch = revision.current;
    request.current?.abort();
    for (const controller of detailRequests.current.values()) controller.abort();
    const busy = kind === 'control' ? setControlling : setDeleting;
    busy(true);
    try { await action(); if (live.current && epoch === revision.current) setError(''); }
    catch (reason) { if (live.current && epoch === revision.current) { mutationError.current = errorText(reason); setError(mutationError.current); } }
    finally {
      mutating.current = false;
      if (live.current && epoch === revision.current) { busy(false); await pending.current; void refresh(); }
    }
  }
  function control(action: 'pause' | 'resume' | 'stop') {
    return mutate(async () => {
      const binding = await qqApi.control(sessionId, action);
      if (live.current && current.current) { current.current = { ...current.current, binding }; setPage(current.current); }
    }, 'control');
  }
  function remove(target: QQDeleteTarget) {
    return mutate(async () => {
      const change = await qqApi.remove(sessionId, target);
      if (live.current && current.current) {
        publish(pruneQQHistory(current.current, change));
        publishDetails({});
      }
    }, 'delete');
  }
  return { page, details, error, loading: !page, historyLoading, paging, controlling, deleting, control, remove,
    loadDetail: (id: string) => loadDetail(id, true),
    setProcessing: (id: string, open: boolean) => {
      if (open) { expanded.current.add(id); void loadDetail(id); }
      else { expanded.current.delete(id); detailRequests.current.get(id)?.abort(); }
    },
    setAnchor: (cursor: string | null) => { anchor.current = cursor; },
    setFollowing: (value: boolean) => { following.current = value; },
    refresh: () => { mutationError.current = ''; return refresh(); }, loadHistory: (mode: QQHistoryDirection) => refresh(mode) };
}
