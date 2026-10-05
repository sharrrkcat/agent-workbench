import { useEffect, useRef, useState } from 'react';
import { qqApi, type QQBinding, type QQMessage, type QQBatch, type QQDelivery, type QQDeleteTarget } from '../../api/qq';
import { toolsApi } from '../../api/tools';
import type { ToolRunResponse } from '../../types/tools';
import { terminal } from '../../store/cogita/mergeState';
import { errorText } from '../settings/resources/ResourceUI';
import { emptyQQRows, olderQQRows, refreshQQRows, QQHistoryChanged, unsettledQQMessage } from './qqConversation';

export function useQQConversation(sessionId: string) {
  const [data, setData] = useState(() => ({ messages: emptyQQRows<QQMessage>(), batches: emptyQQRows<QQBatch>(),
    deliveries: emptyQQRows<QQDelivery>(), runs: {} as Record<string, ToolRunResponse> }));
  const [binding, setBinding] = useState<QQBinding>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const current = useRef(data);
  const live = useRef(false);
  const pending = useRef(false);
  const mutationPending = useRef(false);
  const mutationError = useRef('');
  const revision = useRef(0);

  async function refresh(older = false) {
    if (pending.current || mutationPending.current) return;
    pending.current = true;
    const version = revision.current;
    if (older) setHistoryLoading(true);
    try {
      const saved = current.current;
      const [nextBinding, messages, batches, deliveries] = await Promise.all([
        qqApi.binding(sessionId),
        older ? olderQQRows(saved.messages, (before) => qqApi.messages(sessionId, before))
          : refreshQQRows(saved.messages, (before) => qqApi.messages(sessionId, before), unsettledQQMessage),
        older ? olderQQRows(saved.batches, (before) => qqApi.batches(sessionId, before))
          : refreshQQRows(saved.batches, (before) => qqApi.batches(sessionId, before), (row) => ['queued', 'running'].includes(row.status)),
        older ? olderQQRows(saved.deliveries, (before) => qqApi.deliveries(sessionId, before))
          : refreshQQRows(saved.deliveries, (before) => qqApi.deliveries(sessionId, before), (row) => ['pending', 'sending', 'unknown'].includes(row.status)),
      ]);
      if ([messages, batches, deliveries].some((page) => page.history_version !== nextBinding.history_version))
        throw new QQHistoryChanged();
      const ids = new Set([...batches.items.flatMap((batch) => batch.run_id ? [batch.run_id] : []), ...deliveries.items.map((row) => row.run_id)]);
      const changed = saved.messages.history_version !== nextBinding.history_version;
      const runs = Object.fromEntries(Object.entries(saved.runs).filter(([id]) => ids.has(id) && !changed));
      const results = await Promise.all([...ids].filter((id) => !runs[id] || !terminal(runs[id].run.status))
        .map(async (id) => [id, await toolsApi.getToolRun(id)] as const));
      for (const [id, run] of results) runs[id] = run;
      if (live.current && version === revision.current) {
        current.current = { messages, batches, deliveries, runs };
        setData(current.current); setBinding(nextBinding); setError(mutationError.current); setLoading(false);
      }
    } catch (reason) {
      if (live.current && version === revision.current && !(reason instanceof QQHistoryChanged)) setError(errorText(reason));
    }
    finally { pending.current = false; if (live.current) setHistoryLoading(false); }
  }

  useEffect(() => {
    live.current = true;
    void refresh();
    const timer = setInterval(() => void refresh(), 1500);
    return () => { live.current = false; revision.current++; clearInterval(timer); };
  }, [sessionId]);

  async function control(action: 'pause' | 'resume' | 'stop') {
    if (mutationPending.current) return;
    mutationPending.current = true; mutationError.current = ''; revision.current++; setControlling(true);
    try { const value = await qqApi.control(sessionId, action); if (live.current) { setBinding(value); setError(''); } }
    catch (reason) { if (live.current) { mutationError.current = errorText(reason); setError(mutationError.current); } }
    finally { mutationPending.current = false; if (live.current) { setControlling(false); void refresh(); } }
  }

  async function remove(target: QQDeleteTarget) {
    if (mutationPending.current) return;
    mutationPending.current = true; mutationError.current = ''; revision.current++; setDeleting(true);
    try {
      const change = await qqApi.remove(sessionId, target);
      if (!live.current) return;
      const saved = current.current;
      const removedRuns = new Set(change.deleted_run_ids);
      current.current = {
        messages: { ...saved.messages, items: saved.messages.items.filter((row) => !change.deleted_qq_message_ids.includes(row.id)) },
        deliveries: { ...saved.deliveries, items: saved.deliveries.items.filter((row) => !change.deleted_qq_delivery_ids.includes(row.id) && !removedRuns.has(row.run_id)) },
        batches: { ...saved.batches, items: saved.batches.items.map((row) => row.run_id && removedRuns.has(row.run_id) ? { ...row, run_id: null } : row) },
        runs: Object.fromEntries(Object.entries(saved.runs).filter(([id]) => !removedRuns.has(id)).map(([id, value]) =>
          [id, { ...value, messages: value.messages.filter((message) => !change.deleted_message_ids.includes(message.message_id)) }])),
      };
      setData(current.current); setError('');
    } catch (reason) { if (live.current) { mutationError.current = errorText(reason); setError(mutationError.current); } }
    finally { mutationPending.current = false; if (live.current) { setDeleting(false); void refresh(); } }
  }
  return { ...data, binding, error, loading, historyLoading, controlling, deleting, control, remove,
    refresh: () => { mutationError.current = ''; return refresh(); }, loadOlder: () => refresh(true),
    hasOlder: [data.messages, data.batches, data.deliveries].some((page) => page.next_cursor !== null) };
}
