import { useEffect, useRef, useState } from 'react';
import { qqApi, type QQBinding, type QQMessage, type QQBatch, type QQDelivery } from '../../api/qq';
import { toolsApi } from '../../api/tools';
import type { ToolRunResponse } from '../../types/tools';
import { terminal } from '../../store/cogita/mergeState';
import { errorText } from '../settings/resources/ResourceUI';
import { emptyQQRows, olderQQRows, refreshQQRows } from './qqConversation';

export function useQQConversation(sessionId: string) {
  const [data, setData] = useState(() => ({ messages: emptyQQRows<QQMessage>(), batches: emptyQQRows<QQBatch>(),
    deliveries: emptyQQRows<QQDelivery>(), runs: {} as Record<string, ToolRunResponse> }));
  const [binding, setBinding] = useState<QQBinding>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [controlling, setControlling] = useState(false);
  const current = useRef(data);
  const live = useRef(false);
  const pending = useRef(false);
  const controlPending = useRef(false);
  const revision = useRef(0);

  async function refresh(older = false) {
    if (pending.current || controlPending.current) return;
    pending.current = true;
    const version = revision.current;
    if (older) setHistoryLoading(true);
    try {
      const saved = current.current;
      const [nextBinding, messages, batches, deliveries] = await Promise.all([
        qqApi.binding(sessionId),
        older ? olderQQRows(saved.messages, (before) => qqApi.messages(sessionId, before))
          : refreshQQRows(saved.messages, (before) => qqApi.messages(sessionId, before), (row) => row.disposition === 'pending'),
        older ? olderQQRows(saved.batches, (before) => qqApi.batches(sessionId, before))
          : refreshQQRows(saved.batches, (before) => qqApi.batches(sessionId, before), (row) => ['queued', 'running'].includes(row.status)),
        older ? olderQQRows(saved.deliveries, (before) => qqApi.deliveries(sessionId, before))
          : refreshQQRows(saved.deliveries, (before) => qqApi.deliveries(sessionId, before), (row) => ['pending', 'sending', 'unknown'].includes(row.status)),
      ]);
      const ids = new Set([...batches.items.flatMap((batch) => batch.run_id ? [batch.run_id] : []), ...deliveries.items.map((row) => row.run_id)]);
      const runs = { ...saved.runs };
      const results = await Promise.all([...ids].filter((id) => !runs[id] || !terminal(runs[id].run.status))
        .map(async (id) => [id, await toolsApi.getToolRun(id)] as const));
      for (const [id, run] of results) runs[id] = run;
      if (live.current && version === revision.current) {
        current.current = { messages, batches, deliveries, runs };
        setData(current.current); setBinding(nextBinding); setError(''); setLoading(false);
      }
    } catch (reason) { if (live.current) setError(errorText(reason)); }
    finally { pending.current = false; if (live.current) setHistoryLoading(false); }
  }

  useEffect(() => {
    live.current = true;
    void refresh();
    const timer = setInterval(() => void refresh(), 1500);
    return () => { live.current = false; revision.current++; clearInterval(timer); };
  }, [sessionId]);

  async function control(action: 'pause' | 'resume' | 'stop') {
    if (controlPending.current) return;
    controlPending.current = true; revision.current++; setControlling(true);
    try { const value = await qqApi.control(sessionId, action); if (live.current) { setBinding(value); setError(''); } }
    catch (reason) { if (live.current) setError(errorText(reason)); }
    finally { controlPending.current = false; if (live.current) { setControlling(false); void refresh(); } }
  }
  return { ...data, binding, error, loading, historyLoading, controlling, control,
    refresh: () => refresh(), loadOlder: () => refresh(true),
    hasOlder: [data.messages, data.batches, data.deliveries].some((page) => page.next_cursor !== null) };
}
