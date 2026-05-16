import type { ReactNode } from 'react';
import type { TextMessagePart } from '../../../types';

export function TextPartRenderer({
  part,
  renderMarkdown,
  renderPlainText,
}: {
  part: TextMessagePart;
  renderMarkdown: (text: string) => ReactNode;
  renderPlainText: (text: string) => ReactNode;
}) {
  const text = typeof part.text === 'string' ? part.text : '';
  return part.format === 'markdown' ? <>{renderMarkdown(text)}</> : <>{renderPlainText(text)}</>;
}
