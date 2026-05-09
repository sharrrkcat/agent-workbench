import { ClipboardEvent, DragEvent, FormEvent, KeyboardEvent, ChangeEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { AtSign, Check, ChevronDown, FileText, Octagon, Paperclip, Send, Slash, X } from 'lucide-react';
import { resolveCurrentLlmProfile, useWorkbenchStore } from '../store/useWorkbenchStore';
import type { Agent, Attachment, CapabilityConfig, ImageAttachment, LlmProfile, LlmProviderStatus, Session } from '../types';
import { CommandPalette } from './CommandPalette';
import { capabilitiesFromProfile, ModelCapabilityIcons, type ModelCapabilities } from './ModelCapabilityIcons';
import { resolveAttachmentUrl, type ImagePreview } from '../utils/images';
import { getModelProfileStatus, modelStatusClass, resolveAgentDefaultLlmProfile } from '../utils/modelStatus';

export function ChatInput({ onPreviewImage }: { onPreviewImage: (image: ImagePreview) => void }) {
  const [value, setValue] = useState('');
  const [cursorPosition, setCursorPosition] = useState(0);
  const [suggestionsDismissed, setSuggestionsDismissed] = useState(false);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [isFocused, setIsFocused] = useState(false);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const formRef = useRef<HTMLFormElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const modelSelectorRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const { agents, capabilityConfigs, currentSession, generalSettings, llmProfiles, llmProviderStatuses, sendMessage, sending, cancelActiveRun, updateSessionLlmProfile, refreshProviderStatuses, setError } = useWorkbenchStore();
  const llmDefaults = useWorkbenchStore((state) => state.llmDefaults);

  const canSend = Boolean(currentSession && (value.trim() || attachments.length) && !sending);

  const activeToken = useMemo(() => getActiveToken(value, cursorPosition), [cursorPosition, value]);
  const mode = useMemo(() => {
    if (!activeToken || suggestionsDismissed) return 'none';
    if (activeToken.token.startsWith('/')) return 'commands';
    if (activeToken.token.startsWith('@') && activeToken.token.includes(':')) return 'actions';
    if (activeToken.token.startsWith('@')) return 'agents';
    return 'none';
  }, [activeToken, suggestionsDismissed]);

  const suggestionPanelOpen = mode !== 'none';
  const isCompact = !isFocused && value.trim().length === 0 && attachments.length === 0 && !suggestionPanelOpen && !sending;

  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    if (isCompact) {
      textarea.style.height = '38px';
      textarea.style.overflowY = 'hidden';
      return;
    }
    const nextHeight = Math.min(textarea.scrollHeight, 200);
    textarea.style.height = `${Math.max(nextHeight, 44)}px`;
    textarea.style.overflowY = textarea.scrollHeight > 200 ? 'auto' : 'hidden';
  }, [isCompact, value]);

  useEffect(() => {
    setSuggestionsDismissed(false);
  }, [cursorPosition, value]);

  useEffect(() => {
    function onPointerDown(event: PointerEvent) {
      if (!formRef.current?.contains(event.target as Node)) {
        setSuggestionsDismissed(true);
      }
      if (!modelSelectorRef.current?.contains(event.target as Node)) {
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
        setError(new Error(`${file.name || 'Attachment'} is larger than ${kind === 'image' ? generalSettings?.max_image_size_mb ?? 10 : generalSettings?.max_file_size_mb ?? 10} MB.`), 'Attachment too large');
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

  return (
    <form
      ref={formRef}
      className={`composer-shell ${isCompact ? 'compact' : 'expanded'}`}
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
      <div className="composer-card">
        {dragActive ? <div className="composer-drag-overlay">Drop files to attach</div> : null}
        <CommandPalette mode={mode} token={activeToken?.token ?? ''} onPick={pickSuggestion} />
        <AttachmentPreview attachments={attachments} onRemove={removeAttachment} onPreviewImage={onPreviewImage} />
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => updateValue(event.target.value, event.target.selectionStart)}
          onKeyDown={onKeyDown}
          onKeyUp={(event) => setCursorPosition(event.currentTarget.selectionStart)}
          onPaste={onPaste}
          onSelect={(event) => setCursorPosition(event.currentTarget.selectionStart)}
          placeholder="Ask anything, use @agent, :action, or /command"
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
          <div className="composer-tools" aria-label="Composer tools">
            <button type="button" title="Attach files" onClick={() => fileInputRef.current?.click()} disabled={!currentSession || sending}>
              <Paperclip size={15} />
            </button>
            <button type="button" title="Mention an agent" onClick={() => insertTrigger('@')}>
              <AtSign size={15} />
            </button>
            <button type="button" title="Use a command" onClick={() => insertTrigger('/')}>
              <Slash size={15} />
            </button>
          </div>
          <div className="composer-actions">
            <ModelCapabilityIcons capabilities={capabilities} />
            <div ref={modelSelectorRef} className="model-selector-wrap">
              <button
                className="model-selector-pill"
                type="button"
                title={modelSelectorTitle(currentSession?.llm_profile_id || null, llmProfiles)}
                disabled={!currentSession}
                aria-haspopup="menu"
                aria-expanded={modelMenuOpen}
                onClick={() => setModelMenuOpen((open) => !open)}
              >
                <strong>{selectedModelLabel}</strong>
                <ChevronDown size={13} aria-hidden="true" />
              </button>
              {modelMenuOpen ? (
                <div className="model-selector-menu" role="menu">
                  <button
                    type="button"
                    role="menuitemradio"
                    aria-checked={!currentSession?.llm_profile_id}
                    className={!currentSession?.llm_profile_id ? 'selected' : ''}
                    onClick={() => selectModel(null)}
                    title={defaultModelTitle(agentDefaultProfile, llmProviderStatuses)}
                  >
                    <span className={`model-status-dot ${statusDotClass(agentDefaultProfile, llmProviderStatuses)}`} aria-hidden="true" />
                    <span>Default</span>
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
                        onClick={() => selectModel(profile.id)}
                        title={statusDotTitle(profile, llmProviderStatuses)}
                      >
                        <span className={`model-status-dot ${statusDotClass(profile, llmProviderStatuses)}`} aria-hidden="true" />
                        <span>{profile.name || profile.alias}</span>
                        {selected ? <Check size={14} /> : null}
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>
            <button
              className={`send-button ${sending ? 'stop' : ''}`}
              type={sending ? 'button' : 'submit'}
              disabled={sending ? !currentSession : !canSend}
              title={sending ? 'Stop' : 'Send'}
              onClick={sending ? () => void cancelActiveRun() : undefined}
            >
              {sending ? <Octagon size={17} /> : <Send size={17} />}
              <span className="sr-only">{sending ? 'Stop' : 'Send'}</span>
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
  if (!attachments.length) return null;
  return (
    <div className="composer-attachments">
      {attachments.map((attachment) => (
        <figure className={`composer-attachment ${attachment.type === 'file' ? 'file' : 'image'}`} key={attachment.id}>
          {attachment.type === 'image' ? (
            <button className="composer-attachment-preview" type="button" onClick={() => onPreviewImage({ url: resolveAttachmentUrl(attachment), alt: attachment.name || 'Attached image', title: attachment.name })}>
              <img src={resolveAttachmentUrl(attachment)} alt={attachment.name || 'Attached image'} />
            </button>
          ) : (
            <div className="composer-file-chip" title={attachment.name}>
              <FileText size={18} />
              <span>
                <strong>{attachment.name || 'File'}</strong>
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
            title={`Remove ${attachment.name || 'attachment'}`}
          >
            <X size={14} />
          </button>
        </figure>
      ))}
    </div>
  );
}

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

function modelSelectorTitle(profileId: string | null, profiles: { id: string; name: string; alias: string; model_id: string }[]): string {
  if (!profileId) return 'Default uses the current agent model profile';
  const profile = profiles.find((item) => item.id === profileId);
  if (!profile) return 'Missing model profile';
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

function defaultModelTitle(profile: LlmProfile | undefined, statuses: Record<string, LlmProviderStatus>): string {
  if (!profile) return 'Default: this agent has no model profile.';
  return `Default: ${profile.name || profile.alias}\n${statusDotTitle(profile, statuses)}`;
}

function getActiveToken(value: string, cursorPosition: number): { token: string; start: number; end: number } | null {
  const cursor = Math.max(0, Math.min(cursorPosition, value.length));
  const beforeCursor = value.slice(0, cursor);
  const tokenStart = Math.max(beforeCursor.search(/\S+$/), 0);
  const token = value.slice(tokenStart, cursor);

  if (!token || token.includes(' ') || token.includes('\n') || token.includes('\t')) return null;
  if (!token.startsWith('@') && !token.startsWith('/')) return null;

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
