import { ClipboardEvent, DragEvent, FormEvent, KeyboardEvent, ChangeEvent, forwardRef, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import { AtSign, Check, ChevronDown, FileText, Octagon, Paperclip, Send, Slash, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { resolveCurrentLlmProfile, useWorkbenchStore } from '../store/useWorkbenchStore';
import type { Agent, Attachment, CapabilityConfig, ImageAttachment, LlmProfile, LlmProviderStatus, Session } from '../types';
import { CommandPalette, commandArgumentAutocompleteMode, type CommandPaletteItem } from './CommandPalette';
import { capabilitiesFromProfile, ModelCapabilityIcons, type ModelCapabilities } from './ModelCapabilityIcons';
import { resolveAttachmentUrl, type ImagePreview } from '../utils/images';
import { getModelProfileStatus, modelStatusClass, resolveAgentDefaultLlmProfile } from '../utils/modelStatus';
import { usePopoverPresence } from '../hooks/usePopoverPresence';

export function ChatInput({ onPreviewImage }: { onPreviewImage: (image: ImagePreview) => void }) {
  const { t } = useTranslation('chat');
  const [value, setValue] = useState('');
  const [cursorPosition, setCursorPosition] = useState(0);
  const [suggestionsDismissed, setSuggestionsDismissed] = useState(false);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [isFocused, setIsFocused] = useState(false);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [composerHeight, setComposerHeight] = useState(38);
  const [suggestionItems, setSuggestionItems] = useState<CommandPaletteItem[]>([]);
  const [selectedSuggestionIndex, setSelectedSuggestionIndex] = useState(0);
  const formRef = useRef<HTMLFormElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const modelSelectorRef = useRef<HTMLDivElement | null>(null);
  const modelMenuRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [modelMenuStyle, setModelMenuStyle] = useState<CSSProperties>({});
  const { agents, commands, capabilityConfigs, currentSession, generalSettings, llmProfiles, llmProviderStatuses, sendMessage, sending, cancelActiveRun, updateSessionLlmProfile, refreshProviderStatuses, setError, setComposerDraftText } = useWorkbenchStore();
  const llmDefaults = useWorkbenchStore((state) => state.llmDefaults);
  const modelMenuRendered = usePopoverPresence(modelMenuOpen);

  const canSend = Boolean(currentSession && (value.trim() || attachments.length) && !sending);

  const activeToken = useMemo(() => getActiveToken(value, cursorPosition), [cursorPosition, value]);
  const mode = useMemo(() => {
    if (!activeToken || suggestionsDismissed) return 'none';
    if (activeToken.token.startsWith('/')) return commandArgumentAutocompleteMode(activeToken.token, commands) ? 'command-arguments' : 'commands';
    if (activeToken.token.startsWith('@') && activeToken.token.includes(':')) return 'actions';
    if (activeToken.token.startsWith('@')) return 'agents';
    if (activeToken.token.startsWith(':')) return 'current-actions';
    return 'none';
  }, [activeToken, commands, suggestionsDismissed]);

  const suggestionPanelOpen = mode !== 'none';
  const isCompact = !isFocused && value.trim().length === 0 && attachments.length === 0 && !suggestionPanelOpen && !sending;

  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    let nextHeight = 38;
    let overflowY = 'hidden';
    if (isCompact) {
      nextHeight = 38;
    } else {
      nextHeight = Math.max(Math.min(textarea.scrollHeight, 200), 44);
      overflowY = textarea.scrollHeight > 200 ? 'auto' : 'hidden';
    }
    textarea.style.height = `${nextHeight}px`;
    textarea.style.setProperty('--composer-textarea-height', `${nextHeight}px`);
    textarea.style.overflowY = overflowY;
    setComposerHeight((current) => (current === nextHeight ? current : nextHeight));
  }, [isCompact, value]);

  useEffect(() => {
    setSuggestionsDismissed(false);
  }, [cursorPosition, value]);

  useEffect(() => {
    setSelectedSuggestionIndex(0);
  }, [mode, activeToken?.token]);

  useEffect(() => {
    setComposerDraftText(value);
    return () => setComposerDraftText('');
  }, [setComposerDraftText, value]);

  useEffect(() => {
    function onPointerDown(event: PointerEvent) {
      if (!formRef.current?.contains(event.target as Node)) {
        setSuggestionsDismissed(true);
      }
      const target = event.target as Node;
      if (!modelSelectorRef.current?.contains(target) && !modelMenuRef.current?.contains(target)) {
        setModelMenuOpen(false);
      }
    }
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, []);

  useEffect(() => {
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') {
        setModelMenuOpen(false);
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, []);

  useLayoutEffect(() => {
    if (!modelMenuOpen) return;

    function updateModelMenuPosition() {
      const anchor = modelSelectorRef.current?.getBoundingClientRect();
      if (!anchor) return;
      const width = Math.max(anchor.width, 210);
      const right = Math.max(12, window.innerWidth - anchor.right);
      const maxHeight = Math.max(160, Math.min(260, anchor.top - 20));
      setModelMenuStyle({
        position: 'fixed',
        right,
        bottom: Math.max(12, window.innerHeight - anchor.top + 8),
        width,
        maxHeight,
      });
    }

    updateModelMenuPosition();
    window.addEventListener('resize', updateModelMenuPosition);
    window.addEventListener('scroll', updateModelMenuPosition, true);
    return () => {
      window.removeEventListener('resize', updateModelMenuPosition);
      window.removeEventListener('scroll', updateModelMenuPosition, true);
    };
  }, [modelMenuOpen]);

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!canSend) return;
    const content = value;
    const pendingAttachments = attachments;
    setValue('');
    setAttachments([]);
    setCursorPosition(0);
    setSuggestionsDismissed(true);
    const success = await sendMessage(content, pendingAttachments);
    if (!success) {
      setValue(content);
      setAttachments(pendingAttachments);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Escape' && mode !== 'none') {
      event.preventDefault();
      setSuggestionsDismissed(true);
      return;
    }
    if (mode !== 'none' && suggestionItems.length) {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setSelectedSuggestionIndex((index) => (index + 1) % suggestionItems.length);
        return;
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setSelectedSuggestionIndex((index) => (index - 1 + suggestionItems.length) % suggestionItems.length);
        return;
      }
      if (event.key === 'Tab' || (event.key === 'Enter' && !event.shiftKey)) {
        event.preventDefault();
        pickSuggestion(suggestionItems[Math.min(selectedSuggestionIndex, suggestionItems.length - 1)].value);
        return;
      }
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  }

  async function addFiles(files: FileList | File[]) {
    const fileItems = Array.from(files);
    if (!fileItems.length) return;
    const maxAttachments = generalSettings?.max_attachments_per_message ?? MAX_ATTACHMENTS;
    const maxImageBytes = (generalSettings?.max_image_size_mb ?? 10) * 1024 * 1024;
    const maxFileBytes = (generalSettings?.max_file_size_mb ?? 10) * 1024 * 1024;
    const available = maxAttachments - attachments.length;
    if (available <= 0) {
      setError(new Error(`You can attach up to ${maxAttachments} files.`), 'Too many attachments');
      return;
    }

    const accepted: File[] = [];
    for (const file of fileItems) {
      const kind = inferFileKind(file);
      if (!kind) {
        setError(new Error(`Unsupported file type: ${file.type || file.name}`), 'Unsupported attachment type');
        continue;
      }
      const maxBytes = kind === 'image' ? maxImageBytes : maxFileBytes;
      if (file.size > maxBytes) {
        const size = kind === 'image' ? generalSettings?.max_image_size_mb ?? 10 : generalSettings?.max_file_size_mb ?? 10;
        const message = t('attachmentTooLarge', { name: file.name || t('attachment'), size });
        setError(new Error(message), message);
        continue;
      }
      accepted.push(file);
    }

    if (accepted.length > available) {
      setError(new Error(`Only ${available} more attachment${available === 1 ? '' : 's'} can be added.`), 'Too many attachments');
    }
    const next = await Promise.all(accepted.slice(0, available).map(fileToAttachment));
    if (next.length) setAttachments((current) => [...current, ...next]);
  }

  function removeAttachment(id: string) {
    setAttachments((current) => current.filter((attachment) => attachment.id !== id));
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const files = event.currentTarget.files;
    if (files) void addFiles(files);
    event.currentTarget.value = '';
  }

  function onDragOver(event: DragEvent<HTMLFormElement>) {
    if (!hasFiles(event.dataTransfer)) return;
    event.preventDefault();
    setDragActive(true);
  }

  function onDragLeave(event: DragEvent<HTMLFormElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setDragActive(false);
    }
  }

  function onDrop(event: DragEvent<HTMLFormElement>) {
    if (!hasFiles(event.dataTransfer)) return;
    event.preventDefault();
    setDragActive(false);
    void addFiles(event.dataTransfer.files);
  }

  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const files = Array.from(event.clipboardData.items)
      .filter((item) => item.kind === 'file')
      .map((item) => item.getAsFile())
      .filter((file): file is File => file !== null);
    if (files.length) void addFiles(files);
  }

  function updateValue(nextValue: string, nextCursor: number) {
    setValue(nextValue);
    setCursorPosition(nextCursor);
  }

  function pickSuggestion(replacement: string) {
    if (!activeToken) return;
    const nextValue = `${value.slice(0, activeToken.start)}${replacement}${value.slice(activeToken.end)}`;
    const nextCursor = activeToken.start + replacement.length;
    setValue(nextValue);
    setCursorPosition(nextCursor);
    setSuggestionsDismissed(true);
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(nextCursor, nextCursor);
    });
  }

  function insertTrigger(trigger: '@' | '/') {
    const textarea = textareaRef.current;
    const position = textarea?.selectionStart ?? cursorPosition;
    const needsSpace = value && position > 0 && !/\s/.test(value[position - 1]);
    const insertion = `${needsSpace ? ' ' : ''}${trigger}`;
    const nextValue = `${value.slice(0, position)}${insertion}${value.slice(position)}`;
    const nextCursor = position + insertion.length;
    setValue(nextValue);
    setCursorPosition(nextCursor);
    setSuggestionsDismissed(false);
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(nextCursor, nextCursor);
    });
  }

  const updateSuggestionItems = useCallback((items: CommandPaletteItem[]) => {
    setSuggestionItems((current) => {
      const currentKey = current.map((item) => `${item.key}:${item.value}`).join('|');
      const nextKey = items.map((item) => `${item.key}:${item.value}`).join('|');
      return currentKey === nextKey ? current : items;
    });
    setSelectedSuggestionIndex((index) => Math.min(index, Math.max(items.length - 1, 0)));
  }, []);

  function selectModel(profileId: string | null) {
    setModelMenuOpen(false);
    void updateSessionLlmProfile(profileId).then(() => {
      const selected = profileId ? llmProfiles.find((profile) => profile.id === profileId) : resolveCurrentLlmProfile(useWorkbenchStore.getState());
      if (selected?.provider_profile_id) void refreshProviderStatuses([selected.provider_profile_id]);
    });
  }

  const currentAgent = agents.find((agent) => agent.id === currentSession?.default_agent_id);
  const agentDefaultProfile = resolveAgentDefaultLlmProfile({ agents, capabilityConfigs, currentSession, llmDefaults, llmProfiles });
  const selectedModelLabel = modelSelectorLabel(currentSession?.llm_profile_id || null, llmProfiles, currentAgent, agentDefaultProfile);
  const enabledProfiles = llmProfiles.filter((profile) => profile.enabled);
  const capabilities = getCurrentComposerCapabilities({
    session: currentSession,
    agents,
    capabilityConfigs,
    llmProfiles,
    defaultModelProfileId: llmDefaults?.default_model_profile_id,
    selectedAgentId: currentSession?.default_agent_id,
  });
  const composerStyle = {
    '--composer-textarea-height': `${composerHeight}px`,
  } as CSSProperties;

  return (
    <form
      ref={formRef}
      className={`composer-shell ${isCompact ? 'compact' : 'expanded'}`}
      style={composerStyle}
      onSubmit={submit}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      onFocus={() => setIsFocused(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setIsFocused(false);
        }
      }}
    >
      <CommandPalette mode={mode} token={activeToken?.token ?? ''} selectedIndex={selectedSuggestionIndex} onPick={pickSuggestion} onItemsChange={updateSuggestionItems} />
      <div className="composer-card">
        {dragActive ? <div className="composer-drag-overlay">{t('dropFiles')}</div> : null}
        <AttachmentPreview attachments={attachments} onRemove={removeAttachment} onPreviewImage={onPreviewImage} />
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => updateValue(event.target.value, event.target.selectionStart)}
          onKeyDown={onKeyDown}
          onKeyUp={(event) => setCursorPosition(event.currentTarget.selectionStart)}
          onPaste={onPaste}
          onSelect={(event) => setCursorPosition(event.currentTarget.selectionStart)}
          placeholder={t('placeholder')}
          rows={2}
        />
        <input
          ref={fileInputRef}
          type="file"
          accept={ATTACHMENT_ACCEPT}
          multiple
          className="sr-only"
          tabIndex={-1}
          onChange={onFileChange}
        />
        <div className="composer-toolbar">
          <div className="composer-tools" aria-label={t('tools')}>
            <button type="button" title={t('attachFiles')} onClick={() => fileInputRef.current?.click()} disabled={!currentSession || sending}>
              <Paperclip size={15} />
            </button>
            <button type="button" title={t('mentionAgent')} onClick={() => insertTrigger('@')}>
              <AtSign size={15} />
            </button>
            <button type="button" title={t('useCommand')} onClick={() => insertTrigger('/')}>
              <Slash size={15} />
            </button>
          </div>
          <div className="composer-actions">
            <ModelCapabilityIcons capabilities={capabilities} />
            <div ref={modelSelectorRef} className="model-selector-wrap">
              <button
                className="model-selector-pill"
                type="button"
                title={modelSelectorTitle(currentSession?.llm_profile_id || null, llmProfiles, {
                  defaultTitle: t('defaultModelTitle'),
                  missingProfile: t('missingModelProfile'),
                })}
                disabled={!currentSession}
                aria-haspopup="menu"
                aria-expanded={modelMenuOpen}
                onClick={() => setModelMenuOpen((open) => !open)}
              >
                <strong>{selectedModelLabel}</strong>
                <ChevronDown size={13} aria-hidden="true" />
              </button>
              {modelMenuRendered
                ? createPortal(
                    <ModelSelectorMenu
                      ref={modelMenuRef}
                      style={modelMenuStyle}
                      open={modelMenuOpen}
                      currentSession={currentSession}
                      enabledProfiles={enabledProfiles}
                      agentDefaultProfile={agentDefaultProfile}
                      llmProviderStatuses={llmProviderStatuses}
                      onSelect={selectModel}
                    />,
                    document.body,
                  )
                : null}
            </div>
            <button
              className={`send-button ${sending ? 'stop' : ''}`}
              type={sending ? 'button' : 'submit'}
              disabled={sending ? !currentSession : !canSend}
              title={sending ? t('stop') : t('send')}
              onClick={sending ? () => void cancelActiveRun() : undefined}
            >
              {sending ? <Octagon size={17} /> : <Send size={17} />}
              <span className="sr-only">{sending ? t('stop') : t('send')}</span>
            </button>
          </div>
        </div>
      </div>
    </form>
  );
}

function AttachmentPreview({
  attachments,
  onRemove,
  onPreviewImage,
}: {
  attachments: Attachment[];
  onRemove: (id: string) => void;
  onPreviewImage: (image: ImagePreview) => void;
}) {
  const { t } = useTranslation('chat');
  if (!attachments.length) return null;
  return (
    <div className="composer-attachments">
      {attachments.map((attachment) => (
        <figure className={`composer-attachment ${attachment.type === 'file' ? 'file' : 'image'}`} key={attachment.id}>
          {attachment.type === 'image' ? (
            <button className="composer-attachment-preview" type="button" onClick={() => onPreviewImage({ url: resolveAttachmentUrl(attachment), alt: attachment.name || t('attachedImage'), title: attachment.name })}>
              <img src={resolveAttachmentUrl(attachment)} alt={attachment.name || t('attachedImage')} />
            </button>
          ) : (
            <div className="composer-file-chip" title={attachment.name}>
              <FileText size={18} />
              <span>
                <strong>{attachment.name || t('file')}</strong>
                <small>{fileKindLabel(attachment.mime_type, attachment.name)} · {formatBytes(attachment.size)}</small>
              </span>
            </div>
          )}
          <button
            className="composer-attachment-remove"
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onRemove(attachment.id);
            }}
            title={t('removeAttachment', { name: attachment.name || 'attachment' })}
          >
            <X size={14} />
          </button>
        </figure>
      ))}
    </div>
  );
}

const ModelSelectorMenu = forwardRef<HTMLDivElement, {
  style: CSSProperties;
  open: boolean;
  currentSession?: Session | null;
  enabledProfiles: LlmProfile[];
  agentDefaultProfile?: LlmProfile;
  llmProviderStatuses: Record<string, LlmProviderStatus>;
  onSelect: (profileId: string | null) => void;
}>(
  ({ style, open, currentSession, enabledProfiles, agentDefaultProfile, llmProviderStatuses, onSelect }, ref) => {
    const { t } = useTranslation('chat');
    return (
      <div ref={ref} className={`model-selector-menu model-selector-menu-portal popover-surface ${open ? '' : 'closing'}`} role="menu" style={style} aria-hidden={!open}>
        <button
          type="button"
          role="menuitemradio"
          aria-checked={!currentSession?.llm_profile_id}
          className={!currentSession?.llm_profile_id ? 'selected' : ''}
          onClick={() => onSelect(null)}
          title={defaultModelTitle(agentDefaultProfile, llmProviderStatuses, t('defaultModel'))}
        >
          <span className={`model-status-dot ${statusDotClass(agentDefaultProfile, llmProviderStatuses)}`} aria-hidden="true" />
          <span>{t('defaultModel')}</span>
          {!currentSession?.llm_profile_id ? <Check size={14} /> : null}
        </button>
        {enabledProfiles.map((profile) => {
          const selected = currentSession?.llm_profile_id === profile.id;
          return (
            <button
              key={profile.id}
              type="button"
              role="menuitemradio"
              aria-checked={selected}
              className={selected ? 'selected' : ''}
              onClick={() => onSelect(profile.id)}
              title={statusDotTitle(profile, llmProviderStatuses)}
            >
              <span className={`model-status-dot ${statusDotClass(profile, llmProviderStatuses)}`} aria-hidden="true" />
              <span>{profile.name || profile.alias}</span>
              {selected ? <Check size={14} /> : null}
            </button>
          );
        })}
      </div>
    );
  },
);

ModelSelectorMenu.displayName = 'ModelSelectorMenu';

function fileKindLabel(mimeType: string, name: string): string {
  const extension = fileExtension(name).replace('.', '').toUpperCase();
  return extension || mimeType || 'FILE';
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

type ComposerCapabilitySource = {
  session?: Session;
  agents: Agent[];
  capabilityConfigs: CapabilityConfig[];
  llmProfiles: LlmProfile[];
  defaultModelProfileId?: string | null;
  selectedAgentId?: string | null;
};

export function getCurrentComposerCapabilities({
  session,
  agents,
  capabilityConfigs,
  llmProfiles,
  defaultModelProfileId,
  selectedAgentId,
}: ComposerCapabilitySource): ModelCapabilities {
  const empty = { vision: false, tools: false, reasoning: false, streaming: false };
  const agent = agents.find((item) => item.id === (selectedAgentId || session?.default_agent_id));
  const sessionAllowed = agent?.resolved_runtime?.allow_session_override !== false && agent?.llm?.allow_session_override !== false;
  const sessionProfile = sessionAllowed ? findEnabledProfile(llmProfiles, session?.llm_profile_id) : undefined;
  if (sessionProfile) return profileCapabilities(sessionProfile);

  const agentProfile = findEnabledProfile(llmProfiles, agent?.resolved_runtime?.llm_profile_id || agent?.llm?.profile);
  if (agentProfile) return profileCapabilities(agentProfile);

  const defaultProfile = findEnabledProfile(llmProfiles, defaultModelProfileId);
  if (defaultProfile) return profileCapabilities(defaultProfile);
  const llmConfig = capabilityConfigs.find((config) => config.capability_id === 'llm');
  const fallbackProfileRef = firstStringValue(llmConfig?.resolved_config, 'default_profile') || firstStringValue(llmConfig?.user_config, 'default_profile');
  const fallbackProfile = findEnabledProfile(llmProfiles, fallbackProfileRef);
  return fallbackProfile ? profileCapabilities(fallbackProfile) : empty;
}

function profileCapabilities(profile: LlmProfile): ModelCapabilities {
  return capabilitiesFromProfile(profile);
}

function findEnabledProfile(profiles: LlmProfile[], profileRef?: string | null): LlmProfile | undefined {
  if (!profileRef) return undefined;
  return profiles.find((profile) => profile.enabled && (profile.id === profileRef || profile.alias === profileRef));
}

function firstStringValue(source: Record<string, unknown> | undefined, key: string): string | null {
  const value = source?.[key];
  return typeof value === 'string' && value.trim() ? value : null;
}

function modelSelectorTitle(profileId: string | null, profiles: { id: string; name: string; alias: string; model_id: string }[], labels: { defaultTitle: string; missingProfile: string }): string {
  if (!profileId) return labels.defaultTitle;
  const profile = profiles.find((item) => item.id === profileId);
  if (!profile) return labels.missingProfile;
  return `${profile.name || profile.alias} - ${profile.model_id}`;
}

function modelSelectorLabel(profileId: string | null, profiles: LlmProfile[], agent?: Agent, agentDefaultProfile?: LlmProfile): string {
  if (agent?.resolved_runtime?.allow_session_override === false || agent?.llm?.allow_session_override === false) {
    return agentDefaultProfile ? `Locked: ${agentDefaultProfile.name || agentDefaultProfile.alias}` : 'Locked';
  }
  if (!profileId) {
    return agentDefaultProfile ? `Default: ${agentDefaultProfile.name || agentDefaultProfile.alias}` : 'Default';
  }
  const profile = profiles.find((item) => item.id === profileId);
  return profile ? profile.name || profile.alias : 'Missing profile';
}

function statusDotClass(profile: LlmProfile | undefined, statuses: Record<string, LlmProviderStatus>): string {
  return modelStatusClass(getModelProfileStatus(profile, statuses));
}

function statusDotTitle(profile: LlmProfile | undefined, statuses: Record<string, LlmProviderStatus>): string {
  return getModelProfileStatus(profile, statuses).title;
}

function defaultModelTitle(profile: LlmProfile | undefined, statuses: Record<string, LlmProviderStatus>, defaultLabel: string): string {
  if (!profile) return `${defaultLabel}: this agent has no model profile.`;
  return `${defaultLabel}: ${profile.name || profile.alias}\n${statusDotTitle(profile, statuses)}`;
}

function getActiveToken(value: string, cursorPosition: number): { token: string; start: number; end: number } | null {
  const cursor = Math.max(0, Math.min(cursorPosition, value.length));
  if (cursor === value.length && /^:([A-Za-z0-9_-]*)$/.test(value)) {
    return { token: value, start: 0, end: cursor };
  }
  const beforeCursor = value.slice(0, cursor);
  const slashCommandArgument = beforeCursor.match(/^(\/[a-zA-Z][a-zA-Z0-9_-]*)(?:\s+([^\s]*))?$/);
  if (slashCommandArgument) {
    return { token: beforeCursor, start: 0, end: cursor };
  }
  const tokenStart = Math.max(beforeCursor.search(/\S+$/), 0);
  const token = value.slice(tokenStart, cursor);

  if (!token || token.includes(' ') || token.includes('\n') || token.includes('\t')) return null;
  if (!token.startsWith('@') && !token.startsWith('/') && !token.startsWith(':')) return null;

  return { token, start: tokenStart, end: cursor };
}

const ALLOWED_IMAGE_MIME_TYPES: ImageAttachment['mime_type'][] = ['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/svg+xml'];
const ALLOWED_TEXT_EXTENSIONS = ['.txt', '.md', '.py', '.js', '.ts', '.tsx', '.jsx', '.json', '.yaml', '.yml', '.toml', '.xml', '.html', '.css', '.env', '.log', '.csv', '.sql', '.sh', '.ps1', '.bat', '.ini', '.cfg'];
const ATTACHMENT_ACCEPT = [...ALLOWED_IMAGE_MIME_TYPES, 'image/*', ...ALLOWED_TEXT_EXTENSIONS].join(',');
const MAX_ATTACHMENTS = 10;

async function fileToAttachment(file: File): Promise<Attachment> {
  const dataUrl = await readFileAsDataUrl(file);
  const kind = inferFileKind(file);
  if (kind === 'file') {
    return {
      id: newClientId(),
      type: 'file',
      mime_type: normalizedMimeType(file),
      name: file.name || 'file',
      size: file.size,
      data_url: dataUrl,
    };
  }
  const dimensions = await readImageDimensions(dataUrl).catch(() => ({}));
  return {
    id: newClientId(),
    type: 'image',
    mime_type: normalizedMimeType(file) as ImageAttachment['mime_type'],
    name: file.name || 'image',
    size: file.size,
    data_url: dataUrl,
    ...dimensions,
  };
}

function inferFileKind(file: File): 'image' | 'file' | null {
  const mimeType = normalizedMimeType(file);
  const extension = fileExtension(file.name);
  if (ALLOWED_IMAGE_MIME_TYPES.includes(mimeType as ImageAttachment['mime_type']) || mimeType.startsWith('image/')) return 'image';
  if (ALLOWED_TEXT_EXTENSIONS.includes(extension)) return 'file';
  return null;
}

function normalizedMimeType(file: File): string {
  const fromType = file.type.trim().toLowerCase();
  if (fromType) return fromType;
  const extension = fileExtension(file.name);
  return (
    {
      '.txt': 'text/plain',
      '.md': 'text/markdown',
      '.py': 'text/x-python',
      '.js': 'text/javascript',
      '.ts': 'text/typescript',
      '.tsx': 'text/tsx',
      '.jsx': 'text/jsx',
      '.json': 'application/json',
      '.yaml': 'application/yaml',
      '.yml': 'application/yaml',
      '.toml': 'application/toml',
      '.xml': 'application/xml',
      '.html': 'text/html',
      '.css': 'text/css',
      '.env': 'text/plain',
      '.log': 'text/plain',
      '.csv': 'text/csv',
      '.sql': 'application/sql',
      '.sh': 'application/x-sh',
      '.ps1': 'text/plain',
      '.bat': 'application/bat',
      '.ini': 'text/plain',
      '.cfg': 'text/plain',
    }[extension] || 'application/octet-stream'
  );
}

function fileExtension(name: string): string {
  const match = name.toLowerCase().match(/(\.[^.]+)$/);
  return match ? match[1] : '';
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Failed to read image.'));
    reader.onload = () => {
      if (typeof reader.result === 'string') {
        resolve(reader.result);
        return;
      }
      reject(new Error('Failed to read image.'));
    };
    reader.readAsDataURL(file);
  });
}

function readImageDimensions(dataUrl: string): Promise<Pick<ImageAttachment, 'width' | 'height'>> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve({ width: image.naturalWidth || undefined, height: image.naturalHeight || undefined });
    image.onerror = () => reject(new Error('Image dimensions unavailable.'));
    image.src = dataUrl;
  });
}

function hasFiles(dataTransfer: DataTransfer): boolean {
  return Array.from(dataTransfer.types).includes('Files');
}

function newClientId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
