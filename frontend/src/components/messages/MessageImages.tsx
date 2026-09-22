import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { API_BASE_URL, resolveAttachmentUrlFromBase } from '../../api/url';
import type { Attachment } from '../../types/messages';
import { ImagePreview, type PreviewImage } from './ImagePreview';

export function MessageImages({ attachments }: { attachments: Attachment[] }) {
  const { t } = useTranslation('personas');
  const [preview, setPreview] = useState<PreviewImage | null>(null);
  return <>
    <div className="message-images">
      {attachments.map((item) => {
        const src = resolveAttachmentUrlFromBase(API_BASE_URL, item.uri || `local://attachments/${item.id}`);
        const name = item.name || item.filename || t('image');
        return <button key={item.id} type="button" aria-label={t('previewImage', { name })}
          onClick={() => setPreview({ src, name })}><img src={src} alt={name} loading="lazy" /></button>;
      })}
    </div>
    <ImagePreview image={preview} onClose={() => setPreview(null)} />
  </>;
}
