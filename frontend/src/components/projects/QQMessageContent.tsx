import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { API_BASE_URL, resolveAttachmentUrlFromBase } from '../../api/url';
import type { QQImageSegment, QQSegment, QQDelivery } from '../../api/qq';
import { ImagePreview } from '../messages/ImagePreview';

function QQImage({ segment, onPreview }: { segment: QQImageSegment; onPreview: (mediaId: number) => void }) {
  const { t } = useTranslation('personas');
  const name = segment.description || (segment.kind === 'face' ? segment.label : t(segment.kind === 'sticker' ? 'qq.sticker' : 'image'));
  const attachment = segment.attachment;
  if (segment.status === 'deleted') return <span className="text-muted-foreground" data-qq-media-state="deleted">{t('qq.resources.imagePlaceholder')}</span>;
  if (segment.status !== 'ready' || !attachment) return <span className="text-muted-foreground" data-qq-media-state={segment.status === 'pending' ? 'pending' : 'failed'}>
    {t(segment.status === 'pending' ? 'qq.mediaPending' : 'qq.mediaFailed', { name })}
  </span>;
  return <QQImageButton attachment={attachment} name={name} kind={segment.kind} onPreview={() => onPreview(segment.media_id)} />;
}

function QQImageButton({ attachment, name, kind, onPreview }: {
  attachment: NonNullable<QQImageSegment['attachment']>; name: string; kind: QQImageSegment['kind']; onPreview: () => void;
}) {
  const { t } = useTranslation('personas');
  const [failed, setFailed] = useState(false);
  if (failed) return <span className="text-muted-foreground" data-qq-media-state="failed">{t('qq.mediaFailed', { name })}</span>;
  const src = resolveAttachmentUrlFromBase(API_BASE_URL, attachment.uri);
  return <Button type="button" variant="ghost" className="qq-image-button" data-qq-media-kind={kind}
    aria-label={t('previewImage', { name })} onClick={onPreview}>
    <img src={src} alt={name} width={attachment.width} height={attachment.height} loading="lazy" onError={() => setFailed(true)} />
  </Button>;
}

export function QQDeliveryContent({ delivery }: { delivery: QQDelivery }) {
  const { t } = useTranslation('personas');
  const [open, setOpen] = useState(false);
  const attachment = delivery.attachment;
  if (delivery.kind !== 'text' && delivery.status === 'sent' && delivery.asset_id === null)
    return <div className="message text-muted-foreground" data-qq-media-state="deleted">{t('qq.resources.imagePlaceholder')}</div>;
  if (delivery.kind === 'text' || !attachment) return <div className="message">{delivery.text}</div>;
  const name = delivery.description || delivery.prompt || delivery.text;
  return <div className="message qq-message-content">
    <QQImageButton key={attachment.id} attachment={attachment} name={name} kind="image" onPreview={() => setOpen(true)} />
    <ImagePreview image={open ? { src: resolveAttachmentUrlFromBase(API_BASE_URL, attachment.uri), name } : null} onClose={() => setOpen(false)} />
  </div>;
}

export function QQMessageContent({ segments }: { segments: QQSegment[] }) {
  const { t } = useTranslation('personas');
  const [previewId, setPreview] = useState<number | null>(null);
  const selected = segments.find((segment): segment is QQImageSegment => segment.type === 'image' && segment.media_id === previewId);
  const preview = selected?.attachment ? {
    src: resolveAttachmentUrlFromBase(API_BASE_URL, selected.attachment.uri),
    name: selected.description || (selected.kind === 'face' ? selected.label : t(selected.kind === 'sticker' ? 'qq.sticker' : 'image')),
  } : null;
  return <div className="message qq-message-content">
    {segments.map((segment, index) => segment.type === 'text' ? <span key={index}>{segment.text}</span>
      : <QQImage key={`${segment.media_id}:${segment.attachment?.id ?? ''}`} segment={segment} onPreview={setPreview} />)}
    <ImagePreview image={preview} onClose={() => setPreview(null)} />
  </div>;
}
