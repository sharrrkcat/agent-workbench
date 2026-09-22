import type { Attachment, Message } from '../../types/messages';

export function messageImages(message: Message): Attachment[] {
  const attachments = message.metadata?.attachments;
  return Array.isArray(attachments) ? attachments.filter((item) => item?.type === 'image') : [];
}

export function imageErrorKey(code: string | null | undefined, message: string): string | null {
  if (code === 'REQUEST_TOO_LARGE') return 'personas:imageErrors.tooLarge';
  if (code === 'INVALID_IMAGE') return 'personas:imageErrors.invalid';
  if (code === 'ATTACHMENT_NOT_FOUND') return 'personas:imageErrors.missing';
  if (code === 'UNSUPPORTED_CAPABILITY' && /image|vision/i.test(message)) return 'personas:imageErrors.unsupported';
  return null;
}

export function messageText(message: Message): string {
  return message.parts.filter((part) => part.type === 'text').map((part) => part.text).join('\n\n');
}

export function isContextMessage(message: Message): boolean {
  return ['user', 'assistant', 'tool'].includes(message.role) &&
    !message.metadata?.streaming && !message.metadata?.incomplete && !message.metadata?.event_type &&
    !message.parts.some((part) => part.type === 'error') &&
    (messageImages(message).length > 0 || message.parts.some((part) => part.type !== 'reasoning' && (part.type !== 'text' || part.text.trim())));
}

export function contextMessageLabel(message: Message): string {
  const text = messageText(message).trim();
  if (text) return text.slice(0, 90);
  const images = messageImages(message);
  if (images.length) return images.map((image) => image.name || image.filename || image.id).join(', ').slice(0, 90);
  return message.parts.map((part) =>
    part.type === 'tool_call' || part.type === 'tool_result' ? part.tool_name :
      part.type === 'file' ? part.filename || part.attachment_id :
        part.type === 'image' ? part.title || part.alt || part.attachment_id : '',
  ).filter(Boolean).join(', ').slice(0, 90);
}
