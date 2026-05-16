import type { ReactNode } from 'react';
import type { FileContentPayload, FileMessagePart } from '../../../types';

export function FilePartRenderer({
  part,
  renderFile,
  renderPlainText,
}: {
  part: FileMessagePart;
  renderFile: (payload: FileContentPayload) => ReactNode;
  renderPlainText: (text: string) => ReactNode;
}) {
  if (part.mode === 'inline_text') {
    return <>{renderFile({
      filename: part.filename,
      language: part.language,
      mime_type: part.mime_type,
      content: typeof part.content === 'string' ? part.content : '',
      size: part.size,
      truncated: part.truncated,
    })}</>;
  }
  const label = part.filename || part.attachment_id || part.url || '';
  return <>{renderPlainText(label)}</>;
}
