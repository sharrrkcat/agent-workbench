import { Button } from '@/components/ui/button';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectGroup,
  SelectItem,
} from '@/components/ui/select';
import { Field, FieldLabel } from '@/components/ui/field';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from '@/components/ui/input-group';
import {
  Attachment,
  AttachmentGroup,
  AttachmentMedia,
  AttachmentContent,
  AttachmentTitle,
  AttachmentDescription,
  AttachmentActions,
  AttachmentAction,
} from '@/components/ui/attachment';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Marker, MarkerContent } from '@/components/ui/marker';
import { cn } from '@/lib/utils';
import { FileText, Paperclip, Send, Square, X } from 'lucide-react';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { useModelsStore } from '../store/useModelsStore';
import { useComposerAttachments } from '../hooks/useComposerAttachments';
import { ImagePreview, type PreviewImage } from './messages/ImagePreview';
import { contextMessageLabel, isContextMessage } from './messages/messageContent';

export function ChatInput() {
  const { t } = useTranslation('personas');
  const draft = useWorkbenchStore((state) => state.composerDraftText);
  const setDraft = useWorkbenchStore((state) => state.setComposerDraftText);
  const send = useWorkbenchStore((state) => state.sendMessage);
  const cancelRun = useWorkbenchStore((state) => state.cancelRun);
  const sending = useWorkbenchStore((state) => state.sending);
  const mutatingHistory = useWorkbenchStore((state) => state.mutatingHistory);
  const session = useWorkbenchStore((state) => state.currentSession);
  const messages = useWorkbenchStore((state) => state.messages);
  const sourceMessageId = useWorkbenchStore((state) => state.sourceMessageId);
  const selectSource = useWorkbenchStore((state) => state.setSourceMessageId);
  const sessionEpoch = useWorkbenchStore((state) => state.sessionEpoch);
  const profiles = useModelsStore((state) => state.profiles);
  const activeRun = useWorkbenchStore((state) =>
    [...state.runs]
      .reverse()
      .find((r) => ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(r.status)),
  );
  const { items, attachments, uploading, upload, remove, clear } = useComposerAttachments(sessionEpoch);
  const [preview, setPreview] = useState<PreviewImage | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const contextRequired = session?.effective.context_policy.mode === 'selected_message';
  const eligible = messages.filter(isContextMessage);
  const hasSource = !!sourceMessageId && eligible.some((m) => m.message_id === sourceMessageId);
  const profile = profiles.find((item) => item.id === session?.model_profile_id);
  const hasImages = attachments.some((item) => item.type === 'image');
  const imageIssue =
    hasImages && session?.effective.context_policy.include_attachments !== 'explicit'
      ? t('imagesContextDisabled')
      : hasImages && profile && !profile.capabilities.vision
        ? t('imagesUnsupported')
        : '';
  const cannotSend =
    !session ||
    sending ||
    mutatingHistory ||
    uploading ||
    !!imageIssue ||
    (contextRequired && !hasSource) ||
    (!draft.trim() && attachments.length === 0);

  async function submit() {
    if (cannotSend || activeRun) return;
    const result = await send(draft, attachments);
    if (result && useWorkbenchStore.getState().sessionEpoch === sessionEpoch) {
      setDraft('');
      setPreview(null);
      clear();
    }
  }

  function addFiles(files: File[]) {
    if (files.length && session && !sending && !mutatingHistory) void upload(files);
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
      {items.length ? (
        <AttachmentGroup className="attachment-strip">
          {items.map((item) => (
            <Attachment
              key={item.id}
              state={item.status === 'ready' ? 'done' : item.status}
              className={cn('attachment-chip w-64 flex-nowrap', 'upload-' + item.status)}
            >
              <AttachmentMedia variant={item.preview ? 'image' : 'icon'} className="size-12">
                {item.preview ? (
                  <Button
                    type="button"
                    aria-label={t('previewImage', { name: item.name })}
                    onClick={() => setPreview({ src: item.preview!, name: item.name })}
                    variant="ghost"
                    size="icon"
                    className="attachment-thumbnail size-full overflow-hidden p-0"
                  >
                    <img src={item.preview} alt={item.name} className="size-full object-cover" />
                  </Button>
                ) : (
                  <FileText />
                )}
              </AttachmentMedia>
              <AttachmentContent>
                <AttachmentTitle title={item.name}>{item.name}</AttachmentTitle>
                {item.status === 'uploading' ? (
                  <AttachmentDescription role="status">{t('uploading')}</AttachmentDescription>
                ) : null}
                {item.status === 'error' ? (
                  <AttachmentDescription role="alert" title={item.error}>
                    {t('uploadFailed')} {item.error}
                  </AttachmentDescription>
                ) : null}
              </AttachmentContent>
              <AttachmentActions>
                <AttachmentAction
                  type="button"
                  onClick={() => {
                    setPreview(null);
                    remove(item.id);
                  }}
                  aria-label={t('removeAttachment', { name: item.name })}
                >
                  <X />
                </AttachmentAction>
              </AttachmentActions>
            </Attachment>
          ))}
        </AttachmentGroup>
      ) : null}
      {imageIssue ? (
        <Alert className="composer-warning" variant="destructive">
          <AlertDescription>{imageIssue}</AlertDescription>
        </Alert>
      ) : null}
      {session?.waiting_run_id ? (
        <Marker className="waiting-banner">
          <MarkerContent>{t('waiting')}</MarkerContent>
        </Marker>
      ) : null}
      {contextRequired ? (
        <Field className="composer-context">
          <FieldLabel>{t('selectedContext')}</FieldLabel>
          <Select
            value={hasSource ? sourceMessageId : ''}
            onValueChange={(selected) => selectSource((selected ?? '') || null)}
            items={[
              { value: '', label: t('chooseContext') },
              ...eligible.map((m) => ({
                value: m.message_id,
                label: (
                  <>
                    {m.speaker_name || m.role}: {contextMessageLabel(m)}
                  </>
                ),
              })),
            ]}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectItem value="">{t('chooseContext')}</SelectItem>
                {eligible.map((m) => (
                  <SelectItem key={m.message_id} value={m.message_id}>
                    {m.speaker_name || m.role}: {contextMessageLabel(m)}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
      ) : null}
      <InputGroup className="composer">
        <input
          ref={fileRef}
          type="file"
          multiple
          hidden
          onChange={(event) => {
            addFiles(Array.from(event.target.files || []));
            event.target.value = '';
          }}
        />
        <InputGroupTextarea
          className="max-h-48 min-h-12 px-3"
          value={draft}
          rows={1}
          placeholder={t('messagePlaceholder', { name: session?.effective.persona_name || t('assistant') })}
          aria-label={t('messagePlaceholder', { name: session?.effective.persona_name || t('assistant') })}
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
        <InputGroupAddon align="block-end" className="gap-2">
          <Tooltip>
            <TooltipTrigger
              render={
                <InputGroupButton
                  aria-label={t('attach')}
                  disabled={!session || sending || mutatingHistory}
                  onClick={() => fileRef.current?.click()}
                  size="icon-sm"
                />
              }
            >
              <Paperclip />
            </TooltipTrigger>
            <TooltipContent>{t('attach')}</TooltipContent>
          </Tooltip>
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
                    className="ml-auto"
                  />
                }
              >
                <Square />
              </TooltipTrigger>
              <TooltipContent>{t('cancel')}</TooltipContent>
            </Tooltip>
          ) : (
            <InputGroupButton
              aria-label={t('send')}
              disabled={cannotSend}
              onClick={() => void submit()}
              variant="default"
              size="icon-sm"
              className="ml-auto"
            >
              <Send />
            </InputGroupButton>
          )}
        </InputGroupAddon>
      </InputGroup>
      <Marker className="composer-hint">
        <MarkerContent>
          {dragging
            ? t('dropFiles')
            : hasImages && profile?.source?.type === 'local'
              ? t('localImageLimit')
              : t('imageInputHint')}
        </MarkerContent>
      </Marker>
      <ImagePreview
        image={items.some((item) => item.preview === preview?.src) ? preview : null}
        onClose={() => setPreview(null)}
      />
    </div>
  );
}
