import type { AudioMessagePart } from '../../../types';

export function AudioPartRenderer({ part }: { part: AudioMessagePart }) {
  const url = part.source === 'attachment' && isLocalAttachmentUrl(part.url) ? part.url : '';
  const label = part.title || part.filename || part.attachment_id;
  const details = [part.filename, part.mime_type].filter(Boolean).join(' - ');

  if (!url) {
    return <div className="message-content message-part-notice warning">{label}</div>;
  }

  return (
    <div className="audio-part">
      <div className="audio-part-title">{label}</div>
      <audio controls src={url} />
      {details ? <div className="audio-part-meta">{details}</div> : null}
    </div>
  );
}

function isLocalAttachmentUrl(value: string | null | undefined): value is string {
  return typeof value === 'string' && /^\/api\/attachments\/[A-Za-z0-9_-]+\.[A-Za-z0-9]+$/.test(value);
}
