import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { VideoMessagePart } from '../../../types';

export function VideoPartRenderer({ part }: { part: VideoMessagePart }) {
  const { t } = useTranslation(['renderers']);
  const [failed, setFailed] = useState(false);
  const url = videoSourceUrl(part);
  const poster = part.poster_url && isLocalAttachmentUrl(part.poster_url) ? part.poster_url : undefined;
  const label = part.title || part.filename || (part.source === 'attachment' ? part.attachment_id : part.url);
  const details = [part.filename, part.mime_type, formatBytes(part.size_bytes)].filter(Boolean).join(' - ');

  if (!url) {
    return <div className="message-content message-part-notice warning">{label}</div>;
  }

  return (
    <div className={`video-part ${failed ? 'error' : ''}`}>
      <div className="video-part-header">
        <div className="video-part-title">{label}</div>
        {details ? <div className="video-part-meta">{details}</div> : null}
      </div>
      <video controls preload="metadata" src={url} poster={poster} onError={() => setFailed(true)} />
      {failed ? <div className="video-part-error">{t('video.loadFailed')}</div> : null}
    </div>
  );
}

function isLocalAttachmentUrl(value: string | null | undefined): value is string {
  return typeof value === 'string' && /^\/api\/attachments\/[A-Za-z0-9_-]+\.[A-Za-z0-9]+$/.test(value);
}

function isRemoteHttpUrl(value: string | null | undefined): value is string {
  return typeof value === 'string' && /^https?:\/\//i.test(value);
}

function videoSourceUrl(part: VideoMessagePart): string {
  if (part.source === 'attachment') {
    return isLocalAttachmentUrl(part.url) ? part.url : '';
  }
  if (part.source === 'url') {
    return isRemoteHttpUrl(part.url) ? part.url : '';
  }
  return '';
}

function formatBytes(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '';
  if (value < 1024) return `${value} bytes`;
  const units = ['KB', 'MB', 'GB'];
  let amount = value / 1024;
  let unitIndex = 0;
  while (amount >= 1024 && unitIndex < units.length - 1) {
    amount /= 1024;
    unitIndex += 1;
  }
  const precision = amount >= 10 ? 1 : 2;
  return `${amount.toFixed(precision).replace(/\.0+$/, '')} ${units[unitIndex]}`;
}
