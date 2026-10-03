import { useContext, useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight, Info, Layers, LockKeyhole } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Field, FieldLabel } from '@/components/ui/field';
import { Separator } from '@/components/ui/separator';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';
import { Empty, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { contextPresentation, type DisplayContextSource } from './contextPresentation';
import { useContextTokens } from './useContextTokens';
import { MessageNumbersContext } from './MessageNumbersContext';
import { runsApi } from '../../api/runs';
import type { ContextDetail, ContextSource } from '../../types/context';
import type { RunStep } from '../../types/runs';
import { terminal } from '../../store/cogita/mergeState';
import { ChatAttachments, attachmentSize } from './ChatAttachments';
import type { Reply } from './turns';

export function contextCalls(reply: Reply): RunStep[] {
  return reply.steps.filter((step) => step.kind === 'model' && step.metadata?.context?.available)
    .sort((a, b) => a.order - b.order);
}

export function defaultContextCall(reply: Reply, calls = contextCalls(reply)): string | undefined {
  return calls.find((step) => reply.answer && step.metadata?.llm?.message_id === reply.answer.message_id)?.step_id
    || calls[calls.length - 1]?.step_id;
}

export function ReplyContext({ reply }: { reply: Reply }) {
  const { t } = useTranslation('runs');
  const [open, setOpen] = useState(false);
  useEffect(() => { setOpen(false); }, [reply.run.run_id, reply.run.session_id, reply.run.status]);
  const calls = contextCalls(reply);
  if (reply.run.kind !== 'chat' || !calls.length || (!terminal(reply.run.status) && reply.run.status !== 'WAITING_FOR_USER')) return null;
  return <Dialog open={open} onOpenChange={setOpen}>
    <Tooltip>
      <TooltipTrigger render={<DialogTrigger render={<Button variant="ghost" size="icon" aria-label={t('context.details')} />} />}>
        <Layers data-icon="inline-start" />
      </TooltipTrigger>
      <TooltipContent side="bottom" collisionAvoidance={{ side: 'none', align: 'shift' }}>{t('context.details')}</TooltipContent>
    </Tooltip>
    <DialogContent className="context-dialog sm:max-w-4xl" aria-describedby={undefined}>
      <DialogHeader><DialogTitle>{t('context.details')}</DialogTitle></DialogHeader>
      {open ? <ContextInspector key={reply.run.run_id} reply={reply} calls={calls} /> : null}
    </DialogContent>
  </Dialog>;
}

function ContextInspector({ reply, calls }: { reply: Reply; calls: RunStep[] }) {
  const { t, i18n } = useTranslation('runs');
  const numbers = useContext(MessageNumbersContext);
  const selectId = useId();
  const [callId, setCallId] = useState(() => defaultContextCall(reply, calls));
  const [sourceId, setSourceId] = useState<string>();
  const [tab, setTab] = useState('structure');
  const [retry, setRetry] = useState(0);
  const cache = useRef(new Map<string, ContextDetail>());
  const [loaded, setLoaded] = useState<{ id: string; data?: ContextDetail; failed?: boolean }>();
  const step = calls.find((call) => call.step_id === callId) || calls[calls.length - 1];
  const runId = reply.run.run_id;
  const stepId = step.step_id;
  useEffect(() => {
    const cached = cache.current.get(stepId);
    if (cached) { setLoaded({ id: stepId, data: cached }); return; }
    let current = true;
    const controller = new AbortController();
    setLoaded({ id: stepId });
    runsApi.getContext(runId, stepId, controller.signal).then((data) => {
      if (!current) return;
      cache.current.set(stepId, data);
      setLoaded({ id: stepId, data });
    }, () => { if (current) setLoaded({ id: stepId, failed: true }); });
    return () => { current = false; controller.abort(); };
  }, [runId, stepId, retry]);
  const detail = loaded?.id === stepId ? loaded.data : undefined;
  const presentation = detail ? contextPresentation(detail) : undefined;
  const selected = presentation?.sources.find((source) => source.id === sourceId) || presentation?.sources[0];
  const estimates = useContextTokens(detail);
  const number = new Intl.NumberFormat(i18n.language);
  const count = (value: number | null | undefined) => value == null ? '—' : number.format(value);
  const callsInRun = reply.steps.filter((call) => call.kind === 'model').sort((a, b) => a.order - b.order);
  const items = calls.map((call) => ({ value: call.step_id, label: t('metrics.call', { count: callsInRun.indexOf(call) + 1 }) +
    (reply.answer && call.metadata?.llm?.message_id === reply.answer.message_id ? ` · ${t('context.finalAnswer')}` : '') }));
  const byParent = presentation?.byParent || new Map<string | null, DisplayContextSource[]>();
  const exclusions = presentation?.exclusions || [];
  const tokens = (source: DisplayContextSource) => source.empty ? 0 : estimates?.[source.id];
  const tokenLabel = (source: DisplayContextSource) => tokens(source) == null ? '— tokens' : `≈ ${count(tokens(source))} tokens`;
  const isMessage = (source: ContextSource) => (source.kind === 'history' || source.kind === 'current_input') && !!source.reference_id;
  function label(source: ContextSource) {
    if (source.attachment) return source.attachment.name;
    if (source.citation) return `[${source.citation}] ${source.name || ''}`;
    if (isMessage(source)) {
      const number = numbers.get(source.reference_id!);
      return number == null ? t('context.deletedMessage') : t('context.messageNumber', { number });
    }
    return t(`context.sources.${source.kind}`);
  }
  function sourceNode(source: DisplayContextSource) {
    const children = byParent.get(source.id) || [];
    const row = <div className="context-source-row">
      <Button variant={selected?.id === source.id ? 'secondary' : 'ghost'}
        className="context-source-button h-auto min-h-8 min-w-0 flex-1 justify-between whitespace-normal text-start" aria-pressed={selected?.id === source.id}
        data-context-source={source.kind} data-empty={source.empty || undefined} onClick={() => setSourceId(source.id)}>
        <span className={isMessage(source) ? 'context-message-label' : undefined}>
          {!isMessage(source) && source.kind !== 'system' && !source.parent_id && source.message_index != null ? `${source.message_index + 1}. ` : ''}{label(source)}
        </span>
        {source.empty ? <span>{t('context.empty')}</span> : <span className="context-count"
          style={{ width: `${Math.max(12, count(source.char_count * 4).length + 9)}ch` }}>
          <span className="context-chars">{source.attachment?.type === 'image' ? '—' : t('context.chars', { count: source.char_count })}</span>
          <span className="context-tokens">{tokenLabel(source)}</span>
        </span>}
      </Button>
      {children.length ? <CollapsibleTrigger render={<Button variant="ghost" size="icon-sm" aria-label={t('context.expandSource', { name: label(source) })} />}>
        <ChevronRight data-icon="inline-end" className="context-disclosure" />
      </CollapsibleTrigger> : null}
    </div>;
    return <li key={source.id}>
      {children.length ? <Collapsible defaultOpen={source.kind === 'system'}>
        {row}<CollapsibleContent><ol>{children.map(sourceNode)}</ol></CollapsibleContent>
      </Collapsible> : row}
    </li>;
  }
  return <>
    <div className="context-call-header">
      {calls.length > 1 ? <Field orientation="horizontal" className="w-auto flex-wrap">
        <FieldLabel htmlFor={selectId}>{t('context.modelCall')}</FieldLabel>
        <Select items={items} value={stepId} onValueChange={(value) => { if (value) setCallId(value); }}>
          <SelectTrigger id={selectId} className="w-auto max-w-full" aria-label={t('context.modelCall')}><SelectValue /></SelectTrigger>
          <SelectContent><SelectGroup>{items.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}</SelectGroup></SelectContent>
        </Select>
      </Field> : <span>{items[0].label}</span>}
      <Badge data-context-model>{detail?.model_alias || step.metadata?.llm?.model}</Badge>
      <Badge variant="secondary">{t('context.messages', { count: step.metadata?.context?.message_count ?? 0 })}</Badge>
      <Badge variant="secondary">{t('context.tools', { count: step.metadata?.context?.tool_count ?? 0 })}</Badge>
      <Badge variant="secondary">{t('metrics.inputTokens')}: {count(step.metadata?.llm?.usage?.prompt_tokens)}</Badge>
    </div>
    <div className="context-main">
      {!detail ? <div className="context-feedback" role={loaded?.failed ? 'alert' : 'status'}>
        {loaded?.id === stepId && loaded.failed ? <>
          <span>{t('context.loadFailed')}</span><Button variant="outline" onClick={() => setRetry((value) => value + 1)}>{t('context.retry')}</Button>
        </> : t('context.loading')}
      </div> : <>
        <Tabs className="context-tabs" value={tab} onValueChange={(value) => setTab(String(value))}>
          <TabsList variant="line" aria-label={t('context.view')}>
            <TabsTrigger value="structure">{t('context.structure')}</TabsTrigger>
            <TabsTrigger value="request">{t('context.request')}</TabsTrigger>
          </TabsList>
          <TabsContent value="structure" className="context-structure-panel">
            <div className="context-structure">
              <nav className="context-sources" aria-label={t('context.order')}>
                <ol>{(byParent.get(null) || []).map(sourceNode)}</ol>
              </nav>
              {selected ? <section className="context-source-detail" aria-live="polite">
                <div className="context-source-heading"><span>{label(selected)}</span>{selected.role ? <Badge variant="outline">{selected.role}</Badge> : null}
                  <SourceInfo key={`${stepId}:${selected.id}`} source={selected} tokenLabel={tokenLabel(selected)} />
                </div>
                {selected.attachment ? <>
                  <p className="context-secondary">{selected.attachment.mime_type} · {attachmentSize(selected.attachment.size, i18n.language)}</p>
                  <ChatAttachments items={[selected.attachment]} />
                </> : null}
                {selected.empty ? <Empty><EmptyHeader><EmptyTitle>{t('context.empty')}</EmptyTitle></EmptyHeader></Empty> : <pre className="context-text">{selected.text}</pre>}
              </section> : null}
            </div>
          </TabsContent>
          <TabsContent value="request" className="context-request-panel">
            <p className="context-secondary">{t('context.requestHint')}</p>
            <pre className="context-text context-request">{JSON.stringify(detail.request, null, 2)}</pre>
          </TabsContent>
        </Tabs>
        {exclusions.length ? <Collapsible className="context-exclusions">
          <Separator />
          <CollapsibleTrigger render={<Button variant="ghost" className="justify-start" />}>
            {t('context.exclusions', { count: exclusions.reduce((sum, item) => sum + (item.count ?? 1), 0) })}
            <ChevronRight data-icon="inline-end" className="context-disclosure" />
          </CollapsibleTrigger>
          <CollapsibleContent className="context-exclusions-content"><ul>{exclusions.map((item, index) => <li key={index}>
            <span>{item.name || t(`context.sources.${item.kind}`)}</span>{' · '}{t(`context.reasons.${item.reason}`)}
          </li>)}</ul></CollapsibleContent>
        </Collapsible> : null}
      </>}
    </div>
    {detail ? <div className="context-footer">
      <span><LockKeyhole aria-hidden="true" />{t('context.snapshot')} · {new Date(detail.captured_at).toLocaleString(i18n.language)}</span>
      <span>{t('context.policy', {
        messages: detail.policy.max_messages == null ? t('context.unlimited') : count(detail.policy.max_messages),
        chars: detail.policy.max_chars == null ? t('context.unlimited') : count(detail.policy.max_chars),
      })}</span>
    </div> : null}
  </>;
}

function SourceInfo({ source, tokenLabel }: { source: DisplayContextSource; tokenLabel: string }) {
  const { t, i18n } = useTranslation('runs');
  const [open, setOpen] = useState(false);
  const pressed = useRef(false);
  return <HoverCard open={open} onOpenChange={(next, event) => {
    if (!next && pressed.current && (event.reason === 'trigger-hover' || event.reason === 'trigger-focus')) return;
    if (!next) pressed.current = false;
    setOpen(next);
  }}>
    <HoverCardTrigger delay={150} closeDelay={150} render={<Button variant="ghost" size="icon-sm"
      aria-label={t('context.sourceInfo')} onFocus={() => setOpen(true)} onClick={() => { pressed.current = true; setOpen(true); }} />}>
      <Info data-icon="inline-start" />
    </HoverCardTrigger>
    <HoverCardContent className="context-info" align="start">
      <dl>
        <div><dt>{t('context.characters')}</dt><dd>{source.char_count.toLocaleString(i18n.language)}</dd></div>
        <div><dt>Tokens</dt><dd>{tokenLabel}</dd></div>
        <div><dt>UUID</dt><dd>{source.reference_id || source.attachment?.id || '—'}</dd></div>
        {source.citation ? <div><dt>{t('context.citation')}</dt><dd>{source.citation}</dd></div> : null}
        {source.source_id ? <div><dt>{t('context.sourceId')}</dt><dd>{source.source_id}</dd></div> : null}
        {source.knowledge_base_id ? <div><dt>{t('context.baseId')}</dt><dd>{source.knowledge_base_id}</dd></div> : null}
      </dl>
    </HoverCardContent>
  </HoverCard>;
}
