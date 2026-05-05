import type { Message } from '../types';
import { ActionButtons } from './ActionButtons';

function renderContent(message: Message) {
  if (message.output_type === 'text') return String(message.content ?? '');
  return JSON.stringify(message.content, null, 2);
}

export function MessageBubble({ message }: { message: Message }) {
  const label = message.command_name || message.agent_id || message.role;

  return (
    <article className={`message ${message.role}`}>
      <div className="message-meta">
        <span>{label}</span>
        {message.action_id ? <small>{message.action_id}</small> : null}
      </div>
      <pre>{renderContent(message)}</pre>
      <ActionButtons actions={message.available_actions} />
    </article>
  );
}
