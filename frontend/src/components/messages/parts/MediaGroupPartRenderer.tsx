import type { ReactNode } from 'react';
import type { ImageMessagePart, ImagePayload, MediaGroupMessagePart } from '../../../types';
import { imagePayloadFromPart } from './ImagePartRenderer';

export function MediaGroupPartRenderer({
  part,
  renderImageGallery,
  renderPlainText,
}: {
  part: MediaGroupMessagePart;
  renderImageGallery: (images: ImagePayload[]) => ReactNode;
  renderPlainText: (text: string) => ReactNode;
}) {
  if (part.layout !== 'gallery') return <>{renderPlainText(part.layout)}</>;
  const images = (Array.isArray(part.items) ? part.items : [])
    .filter((item): item is ImageMessagePart => item?.type === 'image')
    .map(imagePayloadFromPart)
    .filter((image): image is ImagePayload => image !== null);
  return images.length ? <>{renderImageGallery(images)}</> : <>{renderPlainText('')}</>;
}
