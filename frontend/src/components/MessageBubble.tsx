import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Bot, CircleAlert, Clock3 } from 'lucide-react';
import type { Agent, Message } from '../types';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { ActionButtons } from './ActionButtons';

export function MessageBubble({ message }: { message: Message }) {
  const agents = useWorkbenchStore((state) => state.agents);

  if (message.output_type === 'error' || message.client_error) {
    return <InlineErrorBlock message={message} />;
  }

  const agent = message.agent_id ? agents.find((item) => item.id === message.agent_id) : undefined;
  const isUser = message.role === 'user';
  const isCommand = message.role === 'command' || Boolean(message.command_name);
  const kind = isUser ? 'user' : isCommand ? 'command' : 'agent';

  return (
    <article className={`message-row ${kind}`}>
      {!isUser ? <AgentAvatar agent={agent} commandName={message.command_name} /> : null}
      <div className="message-stack">
        <MessageHeader message={message} agent={agent} kind={kind} />
        <div className={`message ${kind} ${message.client_status ? message.client_status : ''}`}>
          <MessageContent message={message} />
          {message.client_status === 'pending' ? (
            <div className="message-status">
              <Clock3 size={13} />
              Sending
            </div>
          ) : null}
          <ActionButtons actions={message.available_actions} />
        </div>
      </div>
    </article>
  );
}

function MessageHeader({ message, agent, kind }: { message: Message; agent?: Agent; kind: 'user' | 'agent' | 'command' }) {
  const name = kind === 'user' ? 'You' : message.command_name || agent?.name || message.agent_id || 'Assistant';
  const action = message.action_id && message.action_id !== 'default' ? message.action_id : '';

  return (
    <div className="message-meta">
      <div className="message-title">
        <span>{name}</span>
        {action ? <small>{action}</small> : null}
      </div>
      <time>{formatTime(message.created_at)}</time>
    </div>
  );
}

function AgentAvatar({ agent, commandName }: { agent?: Agent; commandName?: string | null }) {
  const label = commandName || agent?.name || agent?.id || 'AI';
  const avatar = agent?.avatar?.trim();

  return (
    <div className="agent-avatar" aria-hidden="true">
      {avatar || initials(label) || <Bot size={16} />}
    </div>
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

function MessageContent({ message }: { message: Message }) {
  if (message.output_type === 'markdown') {
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
  return { message: contentToText(message.content) };
}

function unwrapJsonString(value: string): string {
  try {
    const parsed = JSON.parse(value);
    return typeof parsed === 'string' ? parsed : value;
  } catch {
    return value;
  }
}

function initials(value: string): string {
  const words = value
    .replace(/[/_-]/g, ' ')
    .split(/\s+/)
    .filter(Boolean);
  return words
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase())
    .join('');
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}
