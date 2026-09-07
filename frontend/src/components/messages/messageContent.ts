import type { Message } from '../../types/messages';

export function messageText(message: Message): string {
  return message.parts.filter((part) => part.type === 'text').map((part) => part.text).join('\n\n');
}

export function isContextMessage(message: Message): boolean {
  return ['user', 'assistant', 'tool'].includes(message.role) &&
    !message.metadata?.streaming && !message.metadata?.incomplete && !message.metadata?.event_type &&
    !message.parts.some((part) => part.type === 'error') &&
    message.parts.some((part) => part.type !== 'reasoning' && (part.type !== 'text' || part.text.trim()));
}

export function contextMessageLabel(message: Message): string {
  const text = messageText(message).trim();
  if (text) return text.slice(0, 90);
  return message.parts.map((part) =>
    part.type === 'tool_call' || part.type === 'tool_result' ? part.tool_name :
      part.type === 'file' ? part.filename || part.attachment_id :
        part.type === 'image' ? part.title || part.alt || part.attachment_id : '',
  ).filter(Boolean).join(', ').slice(0, 90);
}
