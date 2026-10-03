import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from '@/components/ui/input-group';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Marker, MarkerContent } from '@/components/ui/marker';
import { cn } from '@/lib/utils';
import { Paperclip, Plus, ArrowUp, Square } from 'lucide-react';
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';
import { useCogitaStore } from '../store/useCogitaStore';
import { useModelsStore } from '../store/useModelsStore';
import { useComposerAttachments } from '../hooks/useComposerAttachments';
import { useComposerLayout } from '../hooks/useComposerLayout';
import { ChatAttachments } from './messages/ChatAttachments';
import { useChatConfiguration } from '../hooks/useChatConfiguration';
import { ChatModelMenu } from './ChatModelMenu';
import { ContextWindowMeter } from './ContextWindowMeter';
import { configuredContextWindow } from './contextUsage';
import { MessageQueue } from './MessageQueue';

export function ChatInput() {
  const { t } = useTranslation('personas');
  const draft = useCogitaStore((state) => state.composerDraftText);
  const setDraft = useCogitaStore((state) => state.setComposerDraftText);
  const send = useCogitaStore((state) => state.sendMessage);
  const enqueue = useCogitaStore((state) => state.enqueueMessage);
  const beginEdit = useCogitaStore((state) => state.beginQueuedEdit);
  const saveEdit = useCogitaStore((state) => state.saveQueuedEdit);
  const deleteQueued = useCogitaStore((state) => state.deleteQueuedMessage);
  const dispatchQueue = useCogitaStore((state) => state.dispatchQueuedMessage);
  const queue = useCogitaStore((state) => state.currentSession ? state.messageQueues[state.currentSession.session_id] : undefined);
  const cancelRun = useCogitaStore((state) => state.cancelRun);
  const sending = useCogitaStore((state) => state.sending);
  const awaitingAcceptance = useCogitaStore((state) => state.awaitingAcceptance);
  const mutatingHistory = useCogitaStore((state) => state.mutatingHistory);
  const session = useCogitaStore((state) => state.currentSession);
  const chatDraft = useCogitaStore((state) => state.chatDraft);
  const configuration = useChatConfiguration();
  const fullPlaceholder = t('messagePlaceholder', { name: configuration?.persona_name || t('assistant') });
  const { composerRef, textareaRef, measureRef, actionsRef, expanded, textHeight, placeholder } =
    useComposerLayout(draft, fullPlaceholder, t('chat:shortPlaceholder'));
  const sessionLoad = useCogitaStore((state) => state.sessionLoad);
  const ready = !!(session || chatDraft) && (!sessionLoad || sessionLoad.status === 'ready');
  const sessionEpoch = useCogitaStore((state) => state.sessionEpoch);
  const historyLoading = useCogitaStore((state) => state.historyLoading);
  const configurationSaving = useCogitaStore((state) => !!state.currentSession && state.savingSessionIds.includes(state.currentSession.session_id));
  const resolvingApprovals = useCogitaStore((state) => state.resolvingApprovals);
  const profiles = useModelsStore((state) => state.profiles);
  const normalizedRequestLimit = useModelsStore((state) => state.settings?.max_normalized_request_mb);
  const activeRun = useCogitaStore((state) =>
    [...state.runs]
      .reverse()
      .find((r) => ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(r.status)),
  );
  const { items, attachments, uploading, uploadFailed, upload, remove, take, restore, discard } = useComposerAttachments(sessionEpoch);
  const submittedItems = useRef<ReturnType<typeof take> | null>(null);
  const [dragging, setDragging] = useState(false);
  const [configurationBusy, setConfigurationBusy] = useState(false);
  const [queueReady, setQueueReady] = useState<string | null>(null);
  const queueKey = session ? `${sessionEpoch}:${session.session_id}` : null;
  useEffect(() => {
    let live = true;
    if (session && ready) void useCogitaStore.getState().reconcileMessageQueue(session.session_id)
      .then(() => { if (live) setQueueReady(queueKey); });
    return () => { live = false; };
  }, [queueKey, ready]);
  const fileRef = useRef<HTMLInputElement | null>(null);
  useLayoutEffect(() => {
    submittedItems.current = null;
    setDragging(false);
    setConfigurationBusy(false);
    if (fileRef.current) fileRef.current.value = '';
  }, [sessionEpoch]);
  useLayoutEffect(() => {
    if (sending && !awaitingAcceptance && submittedItems.current) {
      discard(submittedItems.current);
      submittedItems.current = null;
    }
  }, [sending, awaitingAcceptance]);
  const profile = profiles.find((item) => item.id === configuration?.model_profile_id);
  const windowIssue = profile?.source?.type === 'provider' && configuredContextWindow(profile) === null
    ? t('chat:contextWindowRequired') : '';
  const hasImages = attachments.some((item) => item.type === 'image');
  const queuedImages = queue?.items[0]?.attachments.some((item) => item.type === 'image');
  const imageIssue =
    hasImages && configuration?.context_policy?.include_attachments !== 'explicit'
      ? t('imagesContextDisabled')
      : '';
  const queueImageIssue = queuedImages && configuration?.context_policy?.include_attachments !== 'explicit';
  useLayoutEffect(() => {
    const target = ready && queueReady === queueKey && !configurationBusy && !windowIssue && !queueImageIssue ? session?.session_id ?? null : null;
    useCogitaStore.setState({ queueTarget: target });
    return () => { useCogitaStore.setState({ queueTarget: null }); };
  }, [session?.session_id, ready, queueReady, queueKey, configurationBusy, windowIssue, queueImageIssue]);
  useEffect(() => {
    void dispatchQueue();
  }, [dispatchQueue, queue, sending, mutatingHistory, historyLoading, session?.waiting_run_id,
    activeRun?.status, session?.session_id, ready, queueReady, configurationBusy, configurationSaving,
    resolvingApprovals, windowIssue, queueImageIssue]);
  const queueMode = !!session && (!!activeRun || sending || !!queue?.items.length || !!queue?.paused || !!queue?.submission);
  const acceptanceLocked = awaitingAcceptance || (!!queue?.submission && !queue.submission.itemId && !queue.submission.accepted);
  const submitLabel = queue?.editing ? t('chat:queue.save') : queueMode ? t('chat:queue.add') : t('send');
  const cannotSend =
    !ready ||
    acceptanceLocked ||
    configurationBusy ||
    configurationSaving ||
    mutatingHistory ||
    uploading ||
    uploadFailed ||
    !!imageIssue ||
    !!windowIssue ||
    (!draft.trim() && attachments.length === 0);

  async function submit() {
    if (cannotSend) return;
    if (queue?.editing) { if (saveEdit()) textareaRef.current?.focus(); return; }
    if (queueMode) {
      if (enqueue(draft, attachments)) discard(take());
      return;
    }
    const batch = take();
    submittedItems.current = batch;
    const result = await send(draft, attachments);
    if (useCogitaStore.getState().sessionEpoch === sessionEpoch && submittedItems.current === batch) {
      if (result) discard(batch);
      else restore(batch);
      submittedItems.current = null;
    }
  }

  function addFiles(files: File[]) {
    if (files.length && ready && !acceptanceLocked && !mutatingHistory) void upload(files);
  }

  return (
    <div
      className={cn('composer-wrap', dragging && 'is-dragging')}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes('Files')) {
          event.preventDefault();
          setDragging(true);
        }
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        addFiles(Array.from(event.dataTransfer.files));
      }}
    >
      <MessageQueue generating={!!activeRun || sending}
        onEdit={(id) => { if (beginEdit(id)) { discard(take()); textareaRef.current?.focus(); } }}
        onDelete={(id) => { const editing = queue?.editing?.id === id; deleteQueued(id); if (editing) textareaRef.current?.focus(); }} />
      <ChatAttachments key={sessionEpoch} items={items} composer onRemove={remove} />
      {imageIssue || windowIssue || queueImageIssue ? (
        <Alert className="composer-warning" variant="destructive">
          <AlertDescription>{imageIssue || windowIssue || t('imagesContextDisabled')}</AlertDescription>
        </Alert>
      ) : null}
      {session?.waiting_run_id ? (
        <Marker className="waiting-banner">
          <MarkerContent>{t('waiting')}</MarkerContent>
        </Marker>
      ) : null}
      <InputGroup
        ref={composerRef}
        data-expanded={expanded}
        className="composer block rounded-[20px] has-[textarea]:rounded-[20px] has-data-[align=block-end]:rounded-[20px] transition-[height] duration-180 ease-out motion-reduce:transition-none"
        style={{
          '--composer-text-height': `min(${textHeight}px, 12rem, 30dvh)`,
          height: expanded
            ? 'calc(var(--composer-text-height) + var(--composer-toolbar-height) + 2px)'
            : 'calc(var(--composer-compact-height) + 2px)',
        } as CSSProperties}
      >
        <input
          ref={fileRef}
          type="file"
          disabled={!ready}
          multiple
          hidden
          onChange={(event) => {
            addFiles(Array.from(event.target.files || []));
            event.target.value = '';
          }}
        />
        <InputGroupTextarea
          ref={textareaRef}
          className="min-h-0 [field-sizing:fixed] transition-[height,padding] duration-180 ease-out motion-reduce:transition-none"
          style={{
            height: expanded ? 'var(--composer-text-height)' : 'var(--composer-compact-height)',
            paddingInlineStart: expanded ? '12px' : 'var(--composer-inline-start)',
            paddingInlineEnd: expanded ? '12px' : 'var(--composer-inline-end)',
            paddingBlock: expanded ? '10px' : 'calc((var(--composer-compact-height) - 1lh) / 2)',
            overflowY: expanded ? 'auto' : 'hidden',
          }}
          disabled={(!session && !chatDraft) || acceptanceLocked}
          value={draft}
          rows={1}
          placeholder={placeholder}
          aria-label={fullPlaceholder}
          onChange={(event) => setDraft(event.currentTarget.value)}
          onPaste={(event) => {
            const files = Array.from(event.clipboardData.files);
            if (files.length) {
              event.preventDefault();
              addFiles(files);
            }
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void submit();
            }
          }}
        />
        <InputGroupAddon align="block-end" className="composer-toolbar absolute inset-x-0 bottom-0 gap-2 pt-1 pointer-events-none [&_button]:pointer-events-auto">
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <InputGroupButton
                  aria-label={t('attach')}
                  disabled={!ready || acceptanceLocked || mutatingHistory}
                  variant="outline"
                  size="icon-sm"
                  className="rounded-full"
                />
              }
            >
              <Plus />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" side="top" className="w-44">
              <DropdownMenuGroup>
                <DropdownMenuItem onClick={() => fileRef.current?.click()}>
                  <Paperclip />
                  {t('chat:addPhotosFiles')}
                </DropdownMenuItem>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
          <div ref={actionsRef} className="ml-auto flex items-center gap-2">
            <ContextWindowMeter key={`context:${sessionEpoch}`} profile={profile}
              generating={!!activeRun && activeRun.status !== 'WAITING_FOR_USER'} />
            <ChatModelMenu key={sessionEpoch} disabled={!ready || sending || mutatingHistory || configurationBusy}
              onBusyChange={setConfigurationBusy} />
            {activeRun ? (
              <Tooltip>
                <TooltipTrigger
                  render={
                    <InputGroupButton
                      disabled={activeRun.status === 'CANCELLING'}
                      aria-label={t('cancel')}
                      onClick={() => void cancelRun(activeRun.run_id)}
                      variant="destructive"
                      size="icon-sm"
                      className="rounded-full"
                    />
                  }
                >
                  <Square />
                </TooltipTrigger>
                <TooltipContent>{t('cancel')}</TooltipContent>
              </Tooltip>
            ) : null}
              <InputGroupButton
                aria-label={submitLabel}
                title={submitLabel}
                disabled={cannotSend}
                onClick={() => void submit()}
                variant="default"
                size="icon-sm"
                className="rounded-full"
              >
                <ArrowUp />
              </InputGroupButton>
          </div>
        </InputGroupAddon>
      </InputGroup>
      <div ref={measureRef} className="composer-measure" aria-hidden="true" />
      {dragging || (hasImages && profile?.source?.type === 'local' && normalizedRequestLimit !== undefined) ? <Marker className="composer-hint">
        <MarkerContent>
          {dragging
            ? t('dropFiles')
            : t('localImageLimit', { limit: normalizedRequestLimit })}
        </MarkerContent>
      </Marker> : null}
    </div>
  );
}
