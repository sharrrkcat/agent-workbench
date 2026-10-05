import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Check, CheckCheck, Clock, CircleHelp, CircleX, LoaderCircle, SkipForward, Pause, Play, Square, Trash2 } from 'lucide-react';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { SidebarTrigger } from '@/components/ui/sidebar';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Bubble, BubbleContent } from '@/components/ui/bubble';
import { Marker, MarkerContent } from '@/components/ui/marker';
import { InputGroupButton } from '@/components/ui/input-group';
import { MessageScrollerButton, MessageScrollerItem, MessageScrollerProvider, useMessageScroller } from '@/components/ui/message-scroller';
import { Empty, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import type { QQMessage, QQDelivery, QQDeleteTarget } from '../../api/qq';
import type { ReplyDeleteAction } from '../messages/ReplyActions';
import type { QQSession } from '../../types/chat';
import type { Run } from '../../types/runs';
import { Feedback, ResourceLoading } from '../settings/resources/ResourceUI';
import { MessageFrame } from '../messages/MessageFrame';
import { RunReply } from '../messages/RunReply';
import { MessageNumbersContext } from '../messages/MessageNumbersContext';
import { ConversationScroller, ConversationViewport, ConversationContent } from '../ConversationSurface';
import { ComposerSurface, ComposerTextarea, ComposerToolbar } from '../ComposerSurface';
import { ContextWindowMeter } from '../ContextWindowMeter';
import { ChatModelMenu } from '../ChatModelMenu';
import { ErrorBanner } from '../ErrorBanner';
import { useComposerLayout } from '../../hooks/useComposerLayout';
import { usePersonaIdentity } from '../../hooks/usePersonaIdentity';
import { useModelsStore } from '../../store/useModelsStore';
import { useCogitaStore } from '../../store/useCogitaStore';
import { terminal } from '../../store/cogita/mergeState';
import { buildQQConversation } from './qqConversation';
import { useQQConversation } from './useQQConversation';
import { QQMessageContent } from './QQMessageContent';

export function QQSessionView({ session }: { session: QQSession }) {
  return <MessageScrollerProvider autoScroll scrollEdgeThreshold={32}>
    <QQConversation session={session} />
  </MessageScrollerProvider>;
}

function QQConversation({ session }: { session: QQSession }) {
  const { t } = useTranslation(['personas', 'chat']);
  const data = useQQConversation(session.session_id);
  const { confirm, confirmation } = useConfirmDialog();
  const deletionDisabled = !data.binding || data.binding.busy || data.deleting || data.controlling;
  async function remove(target: QQDeleteTarget) {
    if (await confirm(t(target.kind === 'reply' ? 'qq.deleteReplyConfirm' : 'qq.deleteMessageConfirm'), { destructive: true }))
      await data.remove(target);
  }
  const { scrollToMessage } = useMessageScroller();
  const viewport = useRef<HTMLDivElement>(null);
  const showFullProcessing = useCogitaStore((state) => state.settings?.show_full_processing === true);
  const items = useMemo(() => buildQQConversation(data.messages.items, data.batches.items, data.deliveries.items, data.runs),
    [data.messages, data.batches, data.deliveries, data.runs]);
  const numbers = useMemo(() => {
    const values = new Map<string, number>();
    let number = 0;
    for (const item of items) {
      values.set(item.id, ++number);
      if (item.kind === 'reply') for (const message of item.reply.messages) values.set(message.message_id, number);
    }
    return values;
  }, [items]);
  async function older() {
    const node = viewport.current;
    const anchor = Array.from(node?.querySelectorAll<HTMLElement>('[data-qq-item]') ?? [])
      .find((row) => row.getBoundingClientRect().bottom > node!.getBoundingClientRect().top);
    const id = anchor?.dataset.messageId;
    const margin = anchor && node ? anchor.getBoundingClientRect().top - node.getBoundingClientRect().top : 0;
    await data.loadOlder();
    if (id) requestAnimationFrame(() => scrollToMessage(id, { align: 'start', behavior: 'instant', scrollMargin: margin }));
  }
  return <>
    <header className="topbar"><SidebarTrigger className="sidebar-toggle" />
      <h1 className="chat-title flex-1" title={session.title}>{session.title || `${t('qq.' + session.target_kind)} ${session.target_id}`}</h1>
    </header>
    <ErrorBanner />
    {data.error || data.binding?.paused ? <div className="px-4 py-2 text-sm">
      <Feedback error={data.error} />
      {data.error && !data.loading ? <Button variant="ghost" size="sm" onClick={() => void data.refresh()}>{t('retry')}</Button> : null}
      {data.binding?.paused ? <p role="status">{t('qq.paused')}: {t('qq.status.' + data.binding.pause_reason, { defaultValue: data.binding.pause_reason })}</p> : null}
    </div> : null}
    <MessageNumbersContext.Provider value={numbers}>
      <ConversationScroller>
        <ConversationViewport ref={viewport} aria-label={t('chat:messages')}
          onClickCapture={(event) => {
            const anchor = (event.target as Element).closest('button[aria-expanded]')?.closest<HTMLElement>('[data-scroll-pause]');
            if (anchor?.dataset.messageId) scrollToMessage(anchor.dataset.messageId, { align: 'nearest', behavior: 'instant' });
          }}>
          <ConversationContent className="qq-conversation gap-0" aria-live="polite">
            {data.hasOlder ? <MessageScrollerItem messageId="qq-older"><Button variant="ghost" size="sm" disabled={data.historyLoading} onClick={() => void older()}>{t('chat:loadEarlier')}</Button></MessageScrollerItem> : null}
            {data.loading ? <MessageScrollerItem messageId="qq-loading"><ResourceLoading error={data.error} retry={() => void data.refresh()} /></MessageScrollerItem>
              : !items.length ? <MessageScrollerItem messageId="qq-empty"><Empty><EmptyHeader><EmptyTitle>{t('qq.empty')}</EmptyTitle></EmptyHeader></Empty></MessageScrollerItem> : null}
            {items.map((item) => <MessageScrollerItem key={item.id} messageId={item.id} data-qq-item
              data-qq-continuation={item.kind === 'incoming' && !item.showIdentity ? '' : undefined}
              scrollAnchor={item.kind === 'incoming'}>
              {item.kind === 'incoming' ? <QQIncoming message={item.message} showIdentity={item.showIdentity}
                deleteAction={{ disabled: deletionDisabled, onDelete: () => void remove({ kind: 'message', id: item.message.id }) }} /> : <>
                <RunReply reply={item.reply} readOnly showFullProcessing={showFullProcessing}
                  deleteAction={{ disabled: deletionDisabled, onDelete: () => void remove({ kind: 'reply', id: item.reply.run.run_id }) }} />
                {item.reply.run.metadata?.qq_reply?.skipped ? <Marker className="mt-2" data-qq-reply-skipped>
                  <MarkerContent>{t('qq.replySkipped')}</MarkerContent>
                </Marker> : null}
                {item.deliveries.length ? <div className="mt-2 flex flex-col gap-1.5" data-qq-deliveries>
                  {item.deliveries.map((delivery) => <QQOutgoing key={delivery.id} delivery={delivery} personaId={item.reply.run.persona_id}
                    deleteAction={{ disabled: deletionDisabled, onDelete: () => void remove({ kind: 'delivery', id: delivery.id }) }} />)}
                </div> : null}
                {item.reply.run.metadata?.qq_reply?.limit_reached ? <Marker className="mt-2" data-qq-reply-limit>
                  <MarkerContent>{t('qq.replyLimitReached', { sent: item.reply.run.metadata.qq_reply.sent_count,
                    limit: item.reply.run.metadata.qq_reply.message_limit })}</MarkerContent>
                </Marker> : null}
              </>}
            </MessageScrollerItem>)}
          </ConversationContent>
        </ConversationViewport>
        <MessageScrollerButton className="latest-message-button" aria-label={t('chat:scrollToEnd')} />
      </ConversationScroller>
    </MessageNumbersContext.Provider>
    <div className="chat-bottom"><QQComposer session={session} runs={Object.values(data.runs).map((value) => value.run)}
      paused={data.binding?.paused === true} controlling={data.controlling || data.deleting || !data.binding} onControl={data.control} /></div>
    {confirmation}
  </>;
}

function QQStatus({ status, detail }: { status: QQMessage['disposition'] | QQDelivery['status']; detail?: string }) {
  const { t } = useTranslation('personas');
  const [open, setOpen] = useState(false);
  const Icon = { pending: Clock, batched: Check, skipped: SkipForward, sending: LoaderCircle,
    sent: CheckCheck, failed: CircleX, unknown: CircleHelp }[status];
  const label = t('qq.status.' + status);
  return <Tooltip open={open} onOpenChange={setOpen}><TooltipTrigger render={<Button variant="ghost" size="icon-sm" aria-label={label} onClick={() => setOpen(true)}
    className={status === 'failed' ? 'shrink-0 text-destructive' : 'shrink-0 text-muted-foreground'} />}>
    <Icon className={status === 'sending' ? 'animate-spin motion-reduce:animate-none' : undefined} />
  </TooltipTrigger><TooltipContent>{label}{detail ? ` · ${detail}` : ''}</TooltipContent></Tooltip>;
}

function QQDeleteButton({ action }: { action: ReplyDeleteAction }) {
  const { t } = useTranslation('personas');
  return <Tooltip><TooltipTrigger render={<Button variant="ghost" size="icon-sm" className="qq-delete shrink-0"
    aria-label={t('qq.deleteMessage')} disabled={action.disabled} onClick={action.onDelete} data-qq-delete />}>
    <Trash2 />
  </TooltipTrigger><TooltipContent side="bottom" collisionAvoidance={{ side: 'none', align: 'shift' }}>{t('qq.deleteMessage')}</TooltipContent></Tooltip>;
}

function QQIncoming({ message, showIdentity, deleteAction }: { message: QQMessage; showIdentity: boolean; deleteAction: ReplyDeleteAction }) {
  const { t } = useTranslation('personas');
  const references = message.references.map((ref) => ref.type === 'reply'
    ? `${t('qq.externalId')}: ${ref.id}`
    : ref.id === 'all' ? t('qq.everyone') : `@${ref.name ?? ref.id} (QQ: ${ref.id})${ref.is_self ? ` · ${t('qq.botSelf')}` : ''}`);
  return <MessageFrame role="user" name={message.sender_name || message.sender_id} createdAt={message.timestamp}
    messageId={`qq-message-${message.id}`} showIdentity={showIdentity} showTime={showIdentity} textAvatar>
    <div className="flex min-w-0 items-center justify-end gap-1" data-qq-bubble-row data-qq-incoming={message.id}>
      <QQDeleteButton action={deleteAction} />
      <QQStatus status={message.disposition} detail={references.join(' · ')} />
      <Bubble variant="secondary" align="end"><BubbleContent className="rounded-[24px] whitespace-pre-wrap"><QQMessageContent segments={message.segments} /></BubbleContent></Bubble>
    </div>
  </MessageFrame>;
}

function QQOutgoing({ delivery, personaId, deleteAction }: { delivery: QQDelivery; personaId: string | null; deleteAction: ReplyDeleteAction }) {
  const { t } = useTranslation('personas');
  const identity = usePersonaIdentity()(personaId);
  const detail = [delivery.error_code ? t('qq.status.' + delivery.error_code, { defaultValue: delivery.error_code }) : '',
    delivery.external_id ? `${t('qq.externalId')}: ${delivery.external_id}` : ''].filter(Boolean).join(' · ');
  return <div data-qq-delivery={delivery.id}>
    <MessageFrame role="assistant" name={identity.name} createdAt={new Date(delivery.created_at * 1000).toISOString()} showIdentity={false} showTime={false}>
      <div className="flex min-w-0 items-center gap-1" data-qq-bubble-row>
        <Bubble variant="secondary"><BubbleContent className="rounded-[24px] whitespace-pre-wrap"><div className="message">{delivery.text}</div></BubbleContent></Bubble>
        <QQStatus status={delivery.status} detail={detail} />
        <QQDeleteButton action={deleteAction} />
      </div>
    </MessageFrame>
  </div>;
}

function QQComposer({ session, runs, paused, controlling, onControl }: {
  session: QQSession; runs: Run[]; paused: boolean; controlling: boolean;
  onControl: (action: 'pause' | 'resume' | 'stop') => Promise<void>;
}) {
  const { t } = useTranslation(['personas', 'chat']);
  const fullPlaceholder = t('qq.chattingIn', { targetId: session.target_id });
  const { composerRef, textareaRef, measureRef, actionsRef, leadingActionsRef, expanded, textHeight, placeholder } =
    useComposerLayout('', fullPlaceholder, fullPlaceholder, true);
  const profile = useModelsStore((state) => state.profiles.find((item) => item.id === session.effective.model_profile_id));
  return <div className="composer-wrap" onDragOver={(event) => event.preventDefault()} onDrop={(event) => event.preventDefault()}>
    <ComposerSurface ref={composerRef} expanded={expanded} textHeight={textHeight}>
      <ComposerTextarea ref={textareaRef} expanded={expanded} disabled value="" rows={1} placeholder={placeholder} aria-label={fullPlaceholder} />
      <ComposerToolbar>
        <div ref={leadingActionsRef} className="flex shrink-0 items-center gap-2">
          <InputGroupButton disabled={controlling} variant="outline" size="sm" className="rounded-full"
            onClick={() => void onControl(paused ? 'resume' : 'pause')}>
            {paused ? <Play data-icon="inline-start" /> : <Pause data-icon="inline-start" />}{t(paused ? 'qq.resume' : 'qq.pause')}
          </InputGroupButton>
          <InputGroupButton disabled={controlling} variant="outline" size="sm" className="rounded-full" onClick={() => void onControl('stop')}>
            <Square data-icon="inline-start" />{t('qq.stop')}
          </InputGroupButton>
        </div>
        <div ref={actionsRef} className="ml-auto flex min-w-0 items-center gap-2">
          <ContextWindowMeter profile={profile} runs={runs} generating={runs.some((run) => !terminal(run.status))} />
          <ChatModelMenu disabled={false} onBusyChange={() => {}} />
        </div>
      </ComposerToolbar>
    </ComposerSurface>
    <div ref={measureRef} className="composer-measure" aria-hidden="true" />
  </div>;
}
