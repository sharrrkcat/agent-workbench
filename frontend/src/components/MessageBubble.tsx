import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Check, ChevronDown, ChevronRight, CircleAlert, Clock3, Copy, Pencil, RefreshCw, Trash2 } from 'lucide-react';
import type { Agent, Message } from '../types';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { ActionButtons } from './ActionButtons';
import { AgentAvatar } from './AgentAvatar';

export function MessageBubble({ message }: { message: Message }) {
  const agents = useWorkbenchStore((state) => state.agents);
  const runs = useWorkbenchStore((state) => state.runs);
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
  const isUser = message.role === 'user';
  const isCommand = message.role === 'command' || Boolean(message.command_name);
  const kind = isUser ? 'user' : isCommand ? 'command' : 'agent';
  const isAgentMessage = message.role === 'assistant' || message.role === 'agent';
  const operationPending = pendingMessageActionId === message.message_id;
  const metricsLabel = isAgentMessage ? formatMetrics(message.metadata?.llm_metrics, Boolean(message.metadata?.interrupted)) : '';
  const reasoningContent = isAgentMessage && message.output_type === 'text' ? extractReasoningContent(message.metadata) : '';

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
      {!isUser ? <AgentAvatar agent={agent} label={message.command_name || undefined} /> : null}
      <div className="message-stack">
        <MessageHeader message={message} agent={agent} kind={kind} modelLabel={resolvedModelLabel(message, runs)} />
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
              <MessageContent message={message} kind={kind} />
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
            {(isUser || isAgentMessage) ? (
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

  return (
    <section className={`thought-block ${expanded ? 'expanded' : ''}`}>
      <button className="thought-toggle" type="button" onClick={() => setExpanded((current) => !current)} aria-expanded={expanded}>
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span>Thought</span>
        {streaming ? <small>Thinking...</small> : null}
      </button>
      {expanded ? <pre className="thought-content">{content}</pre> : null}
    </section>
  );
}

function MessageHeader({
  message,
  agent,
  kind,
  modelLabel,
}: {
  message: Message;
  agent?: Agent;
  kind: 'user' | 'agent' | 'command';
  modelLabel?: string;
}) {
  const name = kind === 'user' ? 'You' : message.command_name || agent?.name || message.agent_id || 'Assistant';
  const action = message.action_id && message.action_id !== 'default' ? message.action_id : '';
  const secondary = modelLabel || action;

  return (
    <div className="message-meta">
      <div className="message-title">
        <span>{name}</span>
        {secondary ? <small title={secondary}>{truncateLabel(secondary)}</small> : null}
      </div>
      <time>{formatTime(message.created_at)}</time>
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

function MessageContent({ message, kind }: { message: Message; kind: 'user' | 'agent' | 'command' }) {
  if (kind === 'user') {
    return <UserPlainTextRenderer content={message.content} />;
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
  return <PlainTextRenderer content={message.content} />;
}

export function PlainTextRenderer({ content }: { content: unknown }) {
  return <div className="message-content plain-text">{contentToText(content)}</div>;
}

function UserPlainTextRenderer({ content }: { content: unknown }) {
  const text = contentToText(content);
  const collapsible = shouldCollapseUserMessage(text);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    setExpanded(false);
  }, [text]);

  return (
    <div className="user-message-content">
      <div className={`message-content plain-text ${collapsible && !expanded ? 'collapsed-user-content' : ''}`}>{text}</div>
      {collapsible ? (
        <button className="message-expand-button" type="button" onClick={() => setExpanded((current) => !current)}>
          {expanded ? 'Show less' : 'Show more'}
        </button>
      ) : null}
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
  if (message.output_type === 'json') {
    return JSON.stringify(normalizeJsonContent(message.content), null, 2);
  }
  return contentToText(message.content);
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

function resolvedModelLabel(message: Message, runs: { run_id: string; metadata?: Record<string, unknown> }[]): string | undefined {
  const fromMessage = extractResolutionLabel(message.metadata?.llm_resolution);
  if (fromMessage) return fromMessage;
  const run = message.run_id ? runs.find((item) => item.run_id === message.run_id) : undefined;
  return extractResolutionLabel(run?.metadata?.llm_resolution);
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

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
