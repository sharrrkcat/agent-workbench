import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Message } from '../types';
import { ActionButtons } from './ActionButtons';

export function MessageBubble({ message }: { message: Message }) {
  const label = message.command_name || message.agent_id || message.role;

  return (
    <article className={`message ${message.role}`}>
      <div className="message-meta">
        <span>{label}</span>
        {message.action_id ? <small>{message.action_id}</small> : null}
      </div>
      <MessageContent message={message} />
      <ActionButtons actions={message.available_actions} />
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

function unwrapJsonString(value: string): string {
  try {
    const parsed = JSON.parse(value);
    return typeof parsed === 'string' ? parsed : value;
  } catch {
    return value;
  }
}
