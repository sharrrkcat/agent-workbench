import type { ReactNode } from 'react';
import type { ImageMessagePart, ImagePayload } from '../../../types';

export function imagePayloadFromPart(part: ImageMessagePart): ImagePayload | null {
  const url = typeof part.url === 'string' && part.url.trim() ? part.url : '';
  if (!url) return null;
  return {
    url,
    alt: part.alt,
    title: part.title,
    caption: part.caption,
  };
}

export function ImagePartRenderer({
  part,
  renderImage,
  renderPlainText,
}: {
  part: ImageMessagePart;
  renderImage: (image: ImagePayload | null) => ReactNode;
  renderPlainText: (text: string) => ReactNode;
}) {
  const image = imagePayloadFromPart(part);
  if (image) return <>{renderImage(image)}</>;
  return <>{renderPlainText(part.alt || part.attachment_id || '')}</>;
}
