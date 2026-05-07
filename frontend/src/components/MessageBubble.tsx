import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Check, ChevronDown, ChevronRight, CircleAlert, Clock3, Copy, FileText, Pencil, RefreshCw, Trash2 } from 'lucide-react';
import type { Agent, Attachment, ChatContentBlock, FileAttachment, FileContentPayload, ImageAttachment, ImagePayload, Message } from '../types';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { ActionButtons } from './ActionButtons';
import { AgentAvatar } from './AgentAvatar';
import { formatMessageTime } from '../utils/time';
import { resolveAttachmentUrl, safeImageUrl, type ImagePreview } from '../utils/images';
import { getResolvedAgentDisplay } from '../utils/agents';

export type FilePreview = {
  url: string;
  name: string;
  mime_type: string;
  size: number;
  language?: string | null;
};

export function MessageBubble({ message, onPreviewImage, onPreviewFile }: { message: Message; onPreviewImage: (image: ImagePreview) => void; onPreviewFile: (file: FilePreview) => void }) {
  const agents = useWorkbenchStore((state) => state.agents);
  const deleteMessage = useWorkbenchStore((state) => state.deleteMessage);
  const retryMessage = useWorkbenchStore((state) => state.retryMessage);
  const editMessage = useWorkbenchStore((state) => state.editMessage);
  const setError = useWorkbenchStore((state) => state.setError);
  const pendingMessageActionId = useWorkbenchStore((state) => state.pendingMessageActionId);
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(contentToText(message.content));

  if (message.output_type === 'event') {
    return <SystemEventSeparator message={message} />;
  }

  if (message.output_type === 'error' || message.client_error || message.metadata?.success === false) {
    return <InlineErrorBlock message={message} />;
  }

  const agent = message.agent_id ? agents.find((item) => item.id === message.agent_id) : undefined;
  const agentDisplay = getResolvedAgentDisplay(agent);
  const isUser = message.role === 'user';
  const isCommand = message.role === 'command' || Boolean(message.command_name);
  const kind = isUser ? 'user' : isCommand ? 'command' : 'agent';
  const isAgentMessage = message.role === 'assistant' || message.role === 'agent';
  const operationPending = pendingMessageActionId === message.message_id;
  const metricsLabel = isAgentMessage ? formatMetrics(message.metadata?.llm_metrics, Boolean(message.metadata?.interrupted)) : '';
  const reasoningContent = isAgentMessage && message.output_type === 'text' ? extractReasoningContent(message.metadata) : '';
  if (!editing && !message.client_status && !hasRenderableMessage(message, reasoningContent)) {
    return null;
  }

  useEffect(() => {
    if (!editing) setEditValue(contentToText(message.content));
  }, [editing, message.content]);

  async function copyMessage() {
    try {
      await navigator.clipboard.writeText(copyableMessageContent(message));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1300);
    } catch (error) {
      setError(error, 'Failed to copy message');
    }
  }

  function confirmDelete() {
    const confirmed = window.confirm('Delete this message?\nThis only removes the selected message.');
    if (!confirmed) return;
    void deleteMessage(message.message_id);
  }

  async function saveEdit() {
    const next = editValue.trim();
    if (!next || operationPending) return;
    try {
      await editMessage(message.message_id, next);
      setEditing(false);
    } catch {
      // The store surfaces the floating error.
    }
  }

  return (
    <article className={`message-row ${kind}`}>
      {!isUser ? <AgentAvatar agent={agentDisplay} label={message.command_name || undefined} /> : null}
      <div className="message-stack">
        <MessageHeader message={message} agent={agent} agentName={agentDisplay.name} kind={kind} modelLabel={resolvedModelLabel(message)} />
        <div className={`message ${kind} ${message.client_status ? message.client_status : ''}`}>
          {editing ? (
            <div className="message-edit-form">
              <textarea value={editValue} onChange={(event) => setEditValue(event.target.value)} rows={Math.min(8, Math.max(3, editValue.split(/\r\n|\r|\n/).length))} />
              <div>
                <button type="button" onClick={() => setEditing(false)} disabled={operationPending}>
                  Cancel
                </button>
                <button type="button" className="primary" onClick={() => void saveEdit()} disabled={!editValue.trim() || operationPending}>
                  Save & submit
                </button>
              </div>
            </div>
          ) : (
            <>
              {reasoningContent ? <ThoughtBlock content={reasoningContent} streaming={message.client_status === 'streaming'} /> : null}
              <MessageContent message={message} kind={kind} onPreviewImage={onPreviewImage} onPreviewFile={onPreviewFile} />
            </>
          )}
          {message.client_status === 'pending' ? (
            <div className="message-status">
              <Clock3 size={13} />
              Sending
            </div>
          ) : null}
          {message.client_status === 'streaming' ? (
            <div className="message-status">
              <Clock3 size={13} />
              Streaming
            </div>
          ) : null}
          <ActionButtons actions={message.available_actions} />
        </div>
        {!message.client_status && !editing ? (
          <div className="message-hover-actions" aria-label="Message actions">
            <button type="button" onClick={() => void copyMessage()} disabled={operationPending} title="Copy">
              {copied ? <Check size={13} /> : <Copy size={13} />}
              {copied ? <span>Copied</span> : ''}
            </button>
            {isAgentMessage ? (
              <button type="button" onClick={() => void retryMessage(message.message_id)} disabled={operationPending} title="Retry">
                <RefreshCw size={13} className={operationPending ? 'spin' : undefined} />
              </button>
            ) : null}
            {isUser ? (
              <button type="button" onClick={() => setEditing(true)} disabled={operationPending} title="Edit">
                <Pencil size={13} />
              </button>
            ) : null}
            {isUser || isAgentMessage || isCommand ? (
              <button type="button" className="danger" onClick={confirmDelete} disabled={operationPending} title="Delete">
                <Trash2 size={13} />
              </button>
            ) : null}
            {metricsLabel ? <span className="message-metrics">{metricsLabel}</span> : null}
          </div>
        ) : null}
      </div>
    </article>
  );
}

function ThoughtBlock({ content, streaming }: { content: string; streaming: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const contentRef = useRef<HTMLPreElement | null>(null);
  const autoScrollRef = useRef(true);

  useLayoutEffect(() => {
    if (!expanded || !streaming || !autoScrollRef.current) return;
    const container = contentRef.current;
    if (!container) return;
    window.requestAnimationFrame(() => {
      if (!autoScrollRef.current) return;
      container.scrollTop = container.scrollHeight;
    });
  }, [content, expanded, streaming]);

  function toggleExpanded() {
    setExpanded((current) => {
      const next = !current;
      if (next) autoScrollRef.current = true;
      return next;
    });
  }

  function handleThoughtScroll() {
    const container = contentRef.current;
    if (!container) return;
    autoScrollRef.current = container.scrollHeight - container.scrollTop - container.clientHeight < 160;
  }

  return (
    <section className={`thought-block ${expanded ? 'expanded' : ''}`}>
      <button className="thought-toggle" type="button" onClick={toggleExpanded} aria-expanded={expanded}>
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span>Thought</span>
        {streaming ? <small>Thinking...</small> : null}
      </button>
      {expanded ? (
        <pre className="thought-content" ref={contentRef} onScroll={handleThoughtScroll}>
          {content}
        </pre>
      ) : null}
    </section>
  );
}

function MessageHeader({
  message,
  agent,
  agentName,
  kind,
  modelLabel,
}: {
  message: Message;
  agent?: Agent;
  agentName?: string;
  kind: 'user' | 'agent' | 'command';
  modelLabel?: string;
}) {
  const name = kind === 'user' ? 'You' : message.command_name || agentName || agent?.name || message.agent_id || 'Assistant';
  const action = message.action_id && message.action_id !== 'default' ? message.action_id : '';
  const secondary = modelLabel || action;

  return (
    <div className="message-meta">
      <div className="message-title">
        <span>{name}</span>
        {secondary ? <small title={secondary}>{truncateLabel(secondary)}</small> : null}
      </div>
      <time>{formatMessageTime(message.created_at)}</time>
    </div>
  );
}

function SystemEventSeparator({ message }: { message: Message }) {
  return (
    <article className="message-row system event">
      <div className="system-event-separator">{contentToText(message.content)}</div>
    </article>
  );
}

function InlineErrorBlock({ message }: { message: Message }) {
  const error = normalizeError(message);

  return (
    <article className="message-row system">
      <div className="inline-error-block">
        <CircleAlert size={16} />
        <div>
          <strong>{error.code || 'Agent failed'}</strong>
          <p>{error.message || 'The run failed.'}</p>
        </div>
      </div>
    </article>
  );
}

function MessageContent({ message, kind, onPreviewImage, onPreviewFile }: { message: Message; kind: 'user' | 'agent' | 'command'; onPreviewImage: (image: ImagePreview) => void; onPreviewFile: (file: FilePreview) => void }) {
  if (kind === 'user') {
    return <UserMessageRenderer content={message.content} attachments={messageAttachments(message)} onPreviewImage={onPreviewImage} onPreviewFile={onPreviewFile} />;
  }
  if (message.output_type === 'markdown') {
    return <MarkdownRenderer content={message.content} />;
  }
  if (message.output_type === 'text' && kind === 'agent') {
    return <MarkdownRenderer content={message.content} />;
  }
  if (message.output_type === 'json') {
    return <JsonRenderer content={message.content} />;
  }
  if (message.output_type === 'file_content') {
    return <FileContentRenderer payload={normalizeFileContentPayload(message.content)} />;
  }
  if (message.output_type === 'image') {
    return <ImageRenderer image={normalizeImagePayload(message.content)} onPreviewImage={onPreviewImage} />;
  }
  if (message.output_type === 'image_gallery') {
    return <ImageGalleryRenderer images={normalizeImageGallery(message.content)} onPreviewImage={onPreviewImage} />;
  }
  if (message.output_type === 'rich_content') {
    return <RichContentRenderer blocks={normalizeRichContentBlocks(message.content)} onPreviewImage={onPreviewImage} />;
  }
  return <PlainTextRenderer content={message.content} />;
}

export function PlainTextRenderer({ content }: { content: unknown }) {
  return <div className="message-content plain-text">{contentToText(content)}</div>;
}

function UserMessageRenderer({ content, attachments, onPreviewImage, onPreviewFile }: { content: unknown; attachments: Attachment[]; onPreviewImage: (image: ImagePreview) => void; onPreviewFile: (file: FilePreview) => void }) {
  const text = contentToText(content);
  const collapsible = shouldCollapseUserMessage(text);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    setExpanded(false);
  }, [text]);

  return (
    <div className="user-message-content">
      {attachments.length ? <AttachmentGallery attachments={attachments} onPreviewImage={onPreviewImage} onPreviewFile={onPreviewFile} /> : null}
      {text ? <div className={`message-content plain-text ${collapsible && !expanded ? 'collapsed-user-content' : ''}`}>{text}</div> : null}
      {collapsible ? (
        <button className="message-expand-button" type="button" onClick={() => setExpanded((current) => !current)}>
          {expanded ? 'Show less' : 'Show more'}
        </button>
      ) : null}
    </div>
  );
}

function AttachmentGallery({ attachments, onPreviewImage, onPreviewFile }: { attachments: Attachment[]; onPreviewImage: (image: ImagePreview) => void; onPreviewFile: (file: FilePreview) => void }) {
  return (
    <div className={`message-attachments ${attachments.length === 1 ? 'single' : 'multi'}`}>
      {attachments.map((attachment) =>
        attachment.type === 'image' ? (
          <figure className="message-attachment" key={attachment.id}>
            <button className="message-image-preview-trigger" type="button" onClick={() => onPreviewImage({ url: attachmentUrl(attachment), alt: attachment.name || 'Attached image', title: attachment.name })}>
              <img src={attachmentUrl(attachment)} alt={attachment.name || 'Attached image'} loading="lazy" />
            </button>
          </figure>
        ) : (
          <button
            className="message-file-chip"
            key={attachment.id}
            type="button"
            onClick={() => {
              const url = resolveAttachmentUrl(attachment);
              if (url) {
                onPreviewFile({
                  url,
                  name: attachment.name || 'File',
                  mime_type: attachment.mime_type,
                  size: attachment.size,
                  language: languageForFilename(attachment.name),
                });
              }
            }}
            title={isPreviewableFile(attachment) ? `Preview ${attachment.name}` : 'Preview not available'}
            disabled={!isPreviewableFile(attachment) || !resolveAttachmentUrl(attachment)}
          >
            <FileText size={18} />
            <span>
              <strong>{attachment.name || 'File'}</strong>
              <small>{fileKindLabel(attachment.mime_type, attachment.name)} · {formatBytes(attachment.size)}</small>
            </span>
          </button>
        ),
      )}
    </div>
  );
}

export function MarkdownRenderer({ content }: { content: unknown }) {
  const markdown = contentToText(content);
  try {
    return (
      <div className="message-content markdown-content">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
      </div>
    );
  } catch {
    return <PlainTextRenderer content={markdown} />;
  }
}

export function JsonRenderer({ content }: { content: unknown }) {
  const parsed = normalizeJsonContent(content);
  if (typeof parsed === 'string') {
    return <pre className="message-content json-content">{parsed}</pre>;
  }
  return <pre className="message-content json-content">{JSON.stringify(parsed, null, 2)}</pre>;
}

export function FileContentRenderer({ payload, variant = 'card', wrapLines }: { payload: FileContentPayload; variant?: 'card' | 'modal'; wrapLines?: boolean }) {
  const setError = useWorkbenchStore((state) => state.setError);
  const [copied, setCopied] = useState(false);
  const filename = payload.filename?.trim() || 'File content';
  const language = payload.language?.trim() || 'text';
  const size = typeof payload.size === 'number' && Number.isFinite(payload.size) ? formatBytes(payload.size) : '';
  const [cardWrapLines, setCardWrapLines] = useState(defaultWrapLines(filename, language));
  const isModal = variant === 'modal';
  const effectiveWrapLines = isModal && typeof wrapLines === 'boolean' ? wrapLines : cardWrapLines;

  async function copyFileContent() {
    try {
      await navigator.clipboard.writeText(payload.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1300);
    } catch (error) {
      setError(error, 'Failed to copy file content');
    }
  }

  return (
    <section className={`message-content file-content-card ${isModal ? 'modal' : 'card'}`}>
      {!isModal ? (
        <header className="file-content-header">
          <div className="file-content-title">
            <strong title={filename}>{filename}</strong>
            <span>{language}</span>
            {size ? <span>{size}</span> : null}
            {payload.truncated ? <span className="file-content-truncated">Truncated</span> : null}
          </div>
          <div className="file-content-actions">
            <button type="button" className="file-content-wrap-toggle" onClick={() => setCardWrapLines((current) => !current)}>
              {effectiveWrapLines ? 'No wrap' : 'Wrap lines'}
            </button>
            <button type="button" className="file-content-copy" onClick={() => void copyFileContent()} title="Copy file content">
              {copied ? <Check size={13} /> : <Copy size={13} />}
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>
          </div>
        </header>
      ) : null}
      {payload.truncated ? <div className="file-content-notice">Content truncated · showing first 1 MB</div> : null}
      <pre className={`file-content-body ${effectiveWrapLines ? 'wrap' : 'no-wrap'}`}>
        <code>{payload.content}</code>
      </pre>
    </section>
  );
}

function ImageRenderer({ image, onPreviewImage }: { image: ImagePayload | null; onPreviewImage: (image: ImagePreview) => void }) {
  if (!image) {
    return <PlainTextRenderer content="" />;
  }
  const url = safeImageUrl(image.url);
  if (!url) {
    return <PlainTextRenderer content={image.caption || image.alt || image.title || ''} />;
  }
  return (
    <figure className="message-content image-content">
      {image.title ? <figcaption className="image-title">{image.title}</figcaption> : null}
      <button className="message-image-preview-trigger" type="button" onClick={() => onPreviewImage({ url, alt: image.alt, title: image.title, caption: image.caption })}>
        <img src={url} alt={image.alt || image.title || image.caption || ''} loading="lazy" />
      </button>
      {image.caption ? <figcaption className="image-caption">{image.caption}</figcaption> : null}
    </figure>
  );
}

function ImageGalleryRenderer({ images, onPreviewImage }: { images: ImagePayload[]; onPreviewImage: (image: ImagePreview) => void }) {
  if (!images.length) {
    return <PlainTextRenderer content="" />;
  }
  return (
    <div className="message-content image-gallery">
      {images.map((image, index) => (
        <ImageRenderer key={`${image.url}-${index}`} image={image} onPreviewImage={onPreviewImage} />
      ))}
    </div>
  );
}

function RichContentRenderer({ blocks, onPreviewImage }: { blocks: ChatContentBlock[]; onPreviewImage: (image: ImagePreview) => void }) {
  if (!blocks.length) {
    return <PlainTextRenderer content="" />;
  }
  return (
    <div className="message-content rich-content">
      {blocks.map((block, index) => {
        if (block.type === 'markdown') {
          return <MarkdownRenderer key={index} content={block.text} />;
        }
        if (block.type === 'image') {
          return <ImageRenderer key={index} image={block} onPreviewImage={onPreviewImage} />;
        }
        if (block.type === 'file_content') {
          return <FileContentRenderer key={index} payload={block} />;
        }
        return <PlainTextRenderer key={index} content={block.text} />;
      })}
    </div>
  );
}

export function contentToText(content: unknown): string {
  if (typeof content === 'string') {
    return unwrapJsonString(content);
  }
  if (content === null || content === undefined) {
    return '';
  }
  if (typeof content === 'object') {
    return JSON.stringify(content, null, 2);
  }
  return String(content);
}

function copyableMessageContent(message: Message): string {
  if (message.output_type === 'file_content') {
    return normalizeFileContentPayload(message.content).content;
  }
  if (message.output_type === 'json') {
    return JSON.stringify(normalizeJsonContent(message.content), null, 2);
  }
  if (['image', 'image_gallery', 'rich_content'].includes(message.output_type)) {
    return JSON.stringify(message.content, null, 2);
  }
  return contentToText(message.content);
}

function messageAttachments(message: Message): Attachment[] {
  const attachments = message.metadata?.attachments;
  if (!Array.isArray(attachments)) return [];
  return attachments.filter(isAttachment);
}

function isAttachment(value: unknown): value is Attachment {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const item = value as Record<string, unknown>;
  const base =
    item.type === 'image' &&
    typeof item.id === 'string' &&
    typeof item.mime_type === 'string' &&
    typeof item.name === 'string' &&
    typeof item.size === 'number' &&
    ((typeof item.data_url === 'string' && Boolean(safeImageUrl(item.data_url))) ||
      (typeof item.uri === 'string' && Boolean(safeImageUrl(item.uri))));
  if (base) return true;
  return item.type === 'file' && typeof item.id === 'string' && typeof item.mime_type === 'string' && typeof item.name === 'string' && typeof item.size === 'number' && (typeof item.uri === 'string' || typeof item.data_url === 'string');
}

function attachmentUrl(attachment: ImageAttachment): string {
  return resolveAttachmentUrl(attachment);
}

function isPreviewableFile(attachment: FileAttachment): boolean {
  const mimeType = attachment.mime_type.toLowerCase();
  const extension = basename(attachment.name)?.toLowerCase().match(/(\.[^.]+)$/)?.[1] || '';
  return mimeType.startsWith('text/') || ['application/json', 'application/xml', 'application/yaml', 'application/toml', 'application/sql'].includes(mimeType) || ['.txt', '.md', '.py', '.js', '.ts', '.tsx', '.jsx', '.json', '.yaml', '.yml', '.toml', '.xml', '.html', '.css', '.env', '.log', '.csv', '.sql', '.sh', '.ps1', '.bat', '.ini', '.cfg'].includes(extension);
}

function fileKindLabel(mimeType: string, name: string): string {
  const extension = basename(name)?.match(/(\.[^.]+)$/)?.[1]?.replace('.', '').toUpperCase();
  return extension || mimeType || 'FILE';
}

function normalizeImagePayload(content: unknown): ImagePayload | null {
  if (!content || typeof content !== 'object' || Array.isArray(content)) return null;
  const value = content as Record<string, unknown>;
  if (typeof value.url !== 'string' || !value.url.trim()) return null;
  return {
    url: value.url,
    alt: optionalString(value.alt),
    title: optionalString(value.title),
    caption: optionalString(value.caption),
  };
}

function normalizeImageGallery(content: unknown): ImagePayload[] {
  if (!content || typeof content !== 'object' || Array.isArray(content)) return [];
  const value = content as Record<string, unknown>;
  if (!Array.isArray(value.images)) return [];
  return value.images.map(normalizeImagePayload).filter((image): image is ImagePayload => image !== null);
}

function normalizeFileContentPayload(content: unknown): FileContentPayload {
  if (!content || typeof content !== 'object' || Array.isArray(content)) {
    return { content: contentToText(content), language: 'text', truncated: false };
  }
  const value = content as Record<string, unknown>;
  return {
    filename: optionalString(value.filename) || basename(optionalString(value.path)),
    language: optionalString(value.language) || 'text',
    mime_type: optionalString(value.mime_type),
    content: typeof value.content === 'string' ? value.content : contentToText(value.content),
    size: numberValue(value.size),
    truncated: value.truncated === true,
    path: optionalString(value.path),
  };
}

function normalizeRichContentBlocks(content: unknown): ChatContentBlock[] {
  if (!content || typeof content !== 'object' || Array.isArray(content)) return [];
  const value = content as Record<string, unknown>;
  if (!Array.isArray(value.blocks)) return [];
  const blocks: ChatContentBlock[] = [];
  for (const block of value.blocks) {
    if (!block || typeof block !== 'object' || Array.isArray(block)) continue;
    const item = block as Record<string, unknown>;
    if (item.type === 'text' && typeof item.text === 'string') {
      blocks.push({ type: 'text', text: item.text });
    } else if (item.type === 'markdown' && typeof item.text === 'string') {
      blocks.push({ type: 'markdown', text: item.text });
    } else if (item.type === 'image') {
      const image = normalizeImagePayload(item);
      if (image) blocks.push({ type: 'image', ...image });
    } else if (item.type === 'file_content') {
      const fileContent = normalizeFileContentPayload(item);
      blocks.push({ type: 'file_content', ...fileContent });
    }
  }
  return blocks;
}

function hasRenderableMessage(message: Message, reasoningContent: string): boolean {
  if (reasoningContent.trim()) return true;
  if (message.output_type === 'image') return normalizeImagePayload(message.content) !== null;
  if (message.output_type === 'image_gallery') return normalizeImageGallery(message.content).length > 0;
  if (message.output_type === 'rich_content') return normalizeRichContentBlocks(message.content).length > 0;
  if (message.output_type === 'file_content') return Boolean(normalizeFileContentPayload(message.content).content.trim());
  if (message.role === 'user' && messageAttachments(message).length) return true;
  return Boolean(contentToText(message.content).trim());
}

function optionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function basename(value: string | undefined): string | undefined {
  if (!value) return undefined;
  return value.split(/[\\/]/).filter(Boolean).pop() || value;
}

function languageForFilename(name: string): string {
  const extension = basename(name)?.toLowerCase().match(/(\.[^.]+)$/)?.[1] || '';
  return (
    {
      '.md': 'markdown',
      '.py': 'python',
      '.js': 'javascript',
      '.ts': 'typescript',
      '.tsx': 'tsx',
      '.jsx': 'jsx',
      '.json': 'json',
      '.yaml': 'yaml',
      '.yml': 'yaml',
      '.toml': 'toml',
      '.xml': 'xml',
      '.html': 'html',
      '.css': 'css',
      '.env': 'dotenv',
      '.log': 'log',
      '.csv': 'csv',
      '.sql': 'sql',
      '.sh': 'shell',
      '.ps1': 'powershell',
      '.bat': 'batch',
      '.ini': 'ini',
      '.cfg': 'ini',
    }[extension] || 'text'
  );
}

export function defaultWrapLines(filename: string, language: string): boolean {
  const extension = basename(filename)?.toLowerCase().match(/(\.[^.]+)$/)?.[1] || '';
  const codeExtensions = new Set(['.py', '.js', '.ts', '.tsx', '.jsx', '.json', '.yaml', '.yml', '.toml', '.xml', '.html', '.css', '.sql', '.sh', '.ps1', '.bat', '.ini', '.cfg']);
  const textExtensions = new Set(['.md', '.txt', '.log', '.csv']);
  if (codeExtensions.has(extension)) return false;
  if (textExtensions.has(extension)) return true;
  return !['python', 'javascript', 'typescript', 'tsx', 'jsx', 'json', 'yaml', 'toml', 'xml', 'html', 'css', 'sql', 'shell', 'powershell', 'batch', 'ini'].includes(language.toLowerCase());
}

function extractReasoningContent(metadata: Record<string, unknown> | undefined): string {
  if (!metadata) return '';
  const direct = metadata.reasoning_content;
  if (typeof direct === 'string' && direct.trim()) return direct;
  const reasoning = metadata.reasoning;
  if (reasoning && typeof reasoning === 'object' && !Array.isArray(reasoning)) {
    const content = (reasoning as Record<string, unknown>).content;
    if (typeof content === 'string' && content.trim()) return content;
  }
  return '';
}

export function normalizeJsonContent(content: unknown): unknown {
  if (typeof content !== 'string') {
    return content;
  }
  const unwrapped = unwrapJsonString(content);
  try {
    return JSON.parse(unwrapped);
  } catch {
    return unwrapped;
  }
}

function normalizeError(message: Message): { code?: string; message?: string } {
  if (message.client_error) {
    return message.client_error;
  }
  if (message.content && typeof message.content === 'object') {
    const content = message.content as Record<string, unknown>;
    return {
      code: typeof content.code === 'string' ? content.code : undefined,
      message: typeof content.message === 'string' ? content.message : undefined,
    };
  }
  return { code: message.run_id ? 'RUN_FAILED' : undefined, message: contentToText(message.content) };
}

function resolvedModelLabel(message: Message): string | undefined {
  const fromMessage = extractResolutionLabel(message.metadata?.llm_resolution);
  if (fromMessage) return fromMessage;
  return undefined;
}

function extractResolutionLabel(value: unknown): string | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const resolution = value as Record<string, unknown>;
  for (const key of ['profile_name', 'profile_key', 'profile_alias', 'model_id']) {
    const item = resolution[key];
    if (typeof item === 'string' && item.trim()) return item.trim();
  }
  return undefined;
}

function formatMetrics(value: unknown, interrupted: boolean): string {
  if (!value || typeof value !== 'object') return '';
  const metrics = value as Record<string, unknown>;
  const usageSource = typeof metrics.usage_source === 'string' ? metrics.usage_source : '';
  const providerTokens = numberValue(metrics.completion_tokens);
  const estimatedTokens = numberValue(metrics.estimated_completion_tokens);
  const tokens = providerTokens ?? estimatedTokens;
  const durationMs = numberValue(metrics.duration_ms);
  const firstTokenMs = numberValue(metrics.time_to_first_token_ms);
  const tokensPerSecond = numberValue(metrics.tokens_per_second);
  const parts: string[] = [];
  if (interrupted) parts.push('Stopped');
  if (tokens !== undefined) {
    const estimated = usageSource === 'estimated' || (providerTokens === undefined && estimatedTokens !== undefined);
    parts.push(`${estimated ? '~' : ''}${tokens} tokens`);
  }
  if (tokensPerSecond !== undefined) {
    parts.push(`${tokensPerSecond.toFixed(1)} tok/s`);
  }
  if (firstTokenMs !== undefined) {
    parts.push(`${formatSeconds(firstTokenMs)} first token`);
  } else if (durationMs !== undefined) {
    parts.push(formatSeconds(durationMs));
  }
  return parts.join(' · ');
}

function numberValue(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  return undefined;
}

function formatSeconds(ms: number): string {
  return `${(ms / 1000).toFixed(ms < 1000 ? 1 : 1)}s`;
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} KB`;
  return `${(value / (1024 * 1024)).toFixed(value < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

function truncateLabel(value: string): string {
  return value.length > 34 ? `${value.slice(0, 31)}...` : value;
}

function unwrapJsonString(value: string): string {
  try {
    const parsed = JSON.parse(value);
    return typeof parsed === 'string' ? parsed : value;
  } catch {
    return value;
  }
}

function shouldCollapseUserMessage(value: string): boolean {
  if (value.length > 600) return true;
  if (value.split(/\r\n|\r|\n/).length > 8) return true;
  return value.split(/\s+/).some((token) => token.length > 160);
}
