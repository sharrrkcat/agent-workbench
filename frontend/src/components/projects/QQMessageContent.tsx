import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { API_BASE_URL, resolveAttachmentUrlFromBase } from '../../api/url';
import type { QQImageSegment, QQSegment } from '../../api/qq';
import { ImagePreview, type PreviewImage } from '../messages/ImagePreview';

function QQImage({ segment, onPreview }: { segment: QQImageSegment; onPreview: (image: PreviewImage) => void }) {
  const { t } = useTranslation('personas');
  const [failed, setFailed] = useState(false);
  const name = segment.kind === 'face' ? segment.label : t(segment.kind === 'sticker' ? 'qq.sticker' : 'image');
  const attachment = segment.attachment;
  if (segment.status !== 'ready' || !attachment || failed) return <span className="text-muted-foreground" data-qq-media-state={segment.status === 'pending' ? 'pending' : 'failed'}>
    {t(segment.status === 'pending' ? 'qq.mediaPending' : 'qq.mediaFailed', { name })}
  </span>;
  const src = resolveAttachmentUrlFromBase(API_BASE_URL, attachment.uri);
  return <Button type="button" variant="ghost" className="qq-image-button" data-qq-media-kind={segment.kind}
    aria-label={t('previewImage', { name })} onClick={() => onPreview({ src, name })}>
    <img src={src} alt={name} width={attachment.width} height={attachment.height} loading="lazy" onError={() => setFailed(true)} />
  </Button>;
}

export function QQMessageContent({ segments }: { segments: QQSegment[] }) {
  const [preview, setPreview] = useState<PreviewImage | null>(null);
  return <div className="message qq-message-content">
    {segments.map((segment, index) => segment.type === 'text' ? <span key={index}>{segment.text}</span>
      : <QQImage key={`${segment.media_id}:${segment.attachment?.id ?? ''}`} segment={segment} onPreview={setPreview} />)}
    <ImagePreview image={preview} onClose={() => setPreview(null)} />
  </div>;
}
