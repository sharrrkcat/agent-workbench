import type { Attachment, Message } from '../../types/messages';

export function messageAttachments(message: Message): Attachment[] {
  const attachments = message.metadata?.attachments;
  return attachments || [];
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

export function messagePreview(message: Message): string {
  const text = messageText(message).trim();
  if (text) return text.slice(0, 90);
  const attachments = messageAttachments(message);
  if (attachments.length) return attachments.map((item) => item.name || item.filename || item.id).join(', ').slice(0, 90);
  return message.parts.map((part) =>
    part.type === 'tool_call' || part.type === 'tool_result' ? part.tool_name :
      part.type === 'file' ? part.filename || part.attachment_id :
        part.type === 'image' ? part.title || part.alt || part.attachment_id : '',
  ).filter(Boolean).join(', ').slice(0, 90);
}
