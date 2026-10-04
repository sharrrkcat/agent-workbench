import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { SidebarTrigger } from '@/components/ui/sidebar';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Message, MessageContent, MessageHeader } from '@/components/ui/message';
import { Bubble, BubbleContent } from '@/components/ui/bubble';
import { MessageScroller, MessageScrollerContent, MessageScrollerItem, MessageScrollerProvider, MessageScrollerViewport } from '@/components/ui/message-scroller';
import { Empty, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { qqApi, type QQBinding, type QQMessage, type QQBatch, type QQDelivery, type QQPage } from '../../api/qq';
import { toolsApi } from '../../api/tools';
import type { ToolRunResponse } from '../../types/tools';
import type { QQSession } from '../../types/chat';
import { Feedback, ResourceLoading, errorText } from '../settings/resources/ResourceUI';
import { RunPanel } from '../RunPanel';
import { ReplyContext } from '../messages/ReplyContext';
import { buildReply } from '../messages/turns';

export function QQSessionView({ session }: { session: QQSession }) {
  const { t } = useTranslation('personas');
  const [binding, setBinding] = useState<QQBinding>();
  const [tab, setTab] = useState('messages');
  const [before, setBefore] = useState<number>();
  const [page, setPage] = useState<QQPage<QQMessage | QQBatch | QQDelivery>>({ items: [], next_cursor: null });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const controlling = useRef(false);
  const revision = useRef(0);
  const [reload, setReload] = useState(0);
  const [runId, setRunId] = useState<string>();
  useEffect(() => {
    let active = true;
    let pending = false;
    const refresh = async () => {
      if (pending || controlling.current) return;
      pending = true;
      const version = revision.current;
      try {
        const [value, rows] = await Promise.all([qqApi.binding(session.session_id),
          tab === 'messages' ? qqApi.messages(session.session_id, before) : tab === 'batches' ? qqApi.batches(session.session_id, before) : qqApi.deliveries(session.session_id, before)]);
        if (active && version === revision.current) { setBinding(value); setPage(rows); setError(''); setLoading(false); }
      } catch (reason) { if (active) setError(errorText(reason)); }
      finally { pending = false; }
    };
    void refresh(); const timer = setInterval(() => void refresh(), 1500);
    return () => { active = false; clearInterval(timer); };
  }, [session.session_id, tab, before, reload]);
  async function control(action: 'pause' | 'resume' | 'stop') {
    if (controlling.current) return;
    controlling.current = true; revision.current++;
    setBusy(true);
    try { setBinding(await qqApi.control(session.session_id, action)); setReload((n) => n + 1); }
    catch (reason) { setError(errorText(reason)); }
    finally { controlling.current = false; setBusy(false); }
  }
  return <>
    <header className="settings-header"><SidebarTrigger /><div className="flex min-w-0 flex-wrap items-center gap-2"><h1 className="min-w-0 flex-1 truncate">{session.title || `${t('qq.' + session.target_kind)} ${session.target_id}`}</h1>
      <Badge variant="secondary">{session.target_id}</Badge>
      <Button variant="outline" disabled={busy || !binding} onClick={() => void control(binding?.paused ? 'resume' : 'pause')}>{t(binding?.paused ? 'qq.resume' : 'qq.pause')}</Button>
      <Button variant="outline" disabled={busy || !binding} onClick={() => void control('stop')}>{t('qq.stop')}</Button>
    </div></header>
    <div className="flex flex-col gap-2 px-4 py-2"><Feedback error={error} />
      {binding?.paused ? <p role="status">{t('qq.paused')}: {t('qq.status.' + binding.pause_reason, { defaultValue: binding.pause_reason })}</p> : null}
      <Tabs value={tab} onValueChange={(value) => { setTab(value); setBefore(undefined); setPage({ items: [], next_cursor: null }); setLoading(true); }}><TabsList>
        <TabsTrigger value="messages">{t('qq.messages')}</TabsTrigger><TabsTrigger value="batches">{t('qq.batches')}</TabsTrigger><TabsTrigger value="deliveries">{t('qq.deliveries')}</TabsTrigger>
      </TabsList></Tabs>
      <div className="flex gap-2"><Button variant="ghost" disabled={loading || !page.next_cursor} onClick={() => { setBefore(page.next_cursor!); setLoading(true); }}>{t('qq.older')}</Button><Button variant="ghost" onClick={() => { setBefore(undefined); setReload((n) => n + 1); }}>{t('qq.latest')}</Button></div>
    </div>
    <MessageScrollerProvider autoScroll={before === undefined}>
      <MessageScroller className="min-h-0 flex-1"><MessageScrollerViewport><MessageScrollerContent className="flex flex-col gap-4 p-4">
        {loading ? <ResourceLoading error={error} retry={() => setReload((n) => n + 1)} /> : page.items.length === 0 ? <Empty><EmptyHeader><EmptyTitle>{t('qq.empty')}</EmptyTitle></EmptyHeader></Empty> : null}
        {[...page.items].reverse().map((row) => <MessageScrollerItem key={`${tab}-${row.id}`} data-message-id={`${tab}-${row.id}`}>
          <Message><MessageContent><MessageHeader className="flex-wrap gap-2">
            {'sender_name' in row ? <span className="wrap-anywhere">{row.sender_name} ({row.sender_id}) · {row.timestamp}</span> : <span>#{row.id} · {new Date(row.created_at * 1000).toLocaleString()}</span>}
            <Badge variant="secondary">{t('qq.status.' + ('disposition' in row ? row.disposition : row.status), { defaultValue: 'disposition' in row ? row.disposition : row.status })}</Badge>
          </MessageHeader><Bubble variant="muted"><BubbleContent className="whitespace-pre-wrap wrap-anywhere">{row.text}</BubbleContent></Bubble>
            {'error_code' in row && row.error_code ? <p>{t('qq.status.' + row.error_code, { defaultValue: row.error_code })}</p> : null}
            {'status' in row && 'external_id' in row && row.external_id ? <span>{t('qq.externalId')}: {row.external_id}</span> : null}
            {'run_id' in row && row.run_id ? <Button variant="ghost" className="self-start" onClick={() => setRunId(row.run_id!)}>{t('qq.inspectRun')}</Button> : null}
          </MessageContent></Message>
        </MessageScrollerItem>)}
      </MessageScrollerContent></MessageScrollerViewport></MessageScroller>
    </MessageScrollerProvider>
    {runId ? <QQRunDetails key={runId} runId={runId} onClose={() => setRunId(undefined)} /> : null}
  </>;
}

function QQRunDetails({ runId, onClose }: { runId: string; onClose: () => void }) {
  const { t } = useTranslation('personas');
  const [data, setData] = useState<ToolRunResponse>();
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    let pending = false;
    let complete = false;
    const refresh = async () => {
      if (pending || complete) return;
      pending = true;
      try {
        const value = await toolsApi.getToolRun(runId);
        if (active) { setData(value); setError(''); }
        complete = ['DONE', 'FAILED', 'CANCELLED', 'INTERRUPTED'].includes(value.run.status);
      } catch (reason) { if (active) setError(errorText(reason)); }
      finally { pending = false; }
    };
    void refresh(); const timer = setInterval(() => void refresh(), 1500);
    return () => { active = false; clearInterval(timer); };
  }, [runId, reload]);
  return <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}><DialogContent className="sm:max-w-3xl"><DialogHeader><DialogTitle>{t('qq.inspectRun')}</DialogTitle></DialogHeader>
    <div className="max-h-[65dvh] overflow-y-auto"><Feedback error={error} />{data ? <>
      <RunPanel run={data.run} /><ReplyContext reply={buildReply(data.run, data.messages, data.run.steps || [])} />
      {data.messages.map((message) => <pre key={message.message_id} className="whitespace-pre-wrap wrap-anywhere">{message.parts.map((part) => 'text' in part ? part.text : JSON.stringify(part)).join('\n')}</pre>)}
    </> : <ResourceLoading error={error} retry={() => setReload((n) => n + 1)} />}</div>
  </DialogContent></Dialog>;
}
