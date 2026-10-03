import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FileText, X } from 'lucide-react';
import {
  Attachment, AttachmentGroup, AttachmentMedia, AttachmentContent, AttachmentTitle,
  AttachmentDescription, AttachmentActions, AttachmentAction, AttachmentTrigger,
} from '@/components/ui/attachment';
import { cn } from '@/lib/utils';
import { API_BASE_URL, resolveAttachmentUrlFromBase } from '../../api/url';
import type { Attachment as StoredAttachment } from '../../types/messages';
import { ImagePreview, type PreviewImage } from './ImagePreview';

export type ChatAttachment = Pick<StoredAttachment, 'id' | 'name' | 'size' | 'mime_type' | 'type' | 'uri'> & {
  preview?: string | null;
  status?: 'uploading' | 'ready' | 'error';
  error?: string;
};

export function attachmentSize(bytes: number, locale: string): string {
  const units = ['B', 'KB', 'MB', 'GB'];
  let unit = 0;
  while (bytes >= 1024 && unit < units.length - 1) { bytes /= 1024; unit++; }
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(bytes)} ${units[unit]}`;
}

export function ChatAttachments({ items, composer = false, onRemove }: {
  items: ChatAttachment[];
  composer?: boolean;
  onRemove?: (id: string) => void;
}) {
  const { t, i18n } = useTranslation('personas');
  const [preview, setPreview] = useState<(PreviewImage & { id: string }) | null>(null);
  if (!items.length) return null;
  return <>
    <AttachmentGroup className={cn('max-w-full px-1 pt-3 pr-3',
      composer ? 'attachment-strip items-end' : 'message-attachments items-start self-end')}>
      {items.map((item) => {
        const isImage = item.type === 'image';
        const src = isImage ? item.preview || resolveAttachmentUrlFromBase(API_BASE_URL,
          item.uri || `local://attachments/${item.id}`) : '';
        const extension = item.name.includes('.') ? item.name.split('.').pop()?.toUpperCase() : '';
        const description = `${extension || item.mime_type || t('renderers:file')} · ${attachmentSize(item.size, i18n.language)}`;
        return <Attachment key={item.id}
          orientation={isImage ? 'vertical' : 'horizontal'}
          state={item.status === 'ready' ? 'done' : item.status || 'done'}
          className={cn(isImage ? composer ? 'w-30' : 'w-40' : 'w-64 flex-nowrap',
            composer && 'attachment-chip', item.status && `upload-${item.status}`)}>
          <AttachmentMedia variant={isImage ? 'image' : 'icon'}>
            {isImage && (item.preview || item.status !== 'uploading') ? <img src={src} alt={item.name} loading="lazy" /> : <FileText />}
          </AttachmentMedia>
          {composer || !isImage ? <AttachmentContent>
            <AttachmentTitle title={item.name}>{item.name}</AttachmentTitle>
            <AttachmentDescription title={description}>{description}</AttachmentDescription>
            {item.status === 'uploading' ? <AttachmentDescription role="status">{t('uploading')}</AttachmentDescription> : null}
            {item.status === 'error' ? <AttachmentDescription role="alert" title={item.error}>
              {t('uploadFailed')} {item.error}
            </AttachmentDescription> : null}
          </AttachmentContent> : null}
          {isImage ? <AttachmentTrigger className="attachment-thumbnail"
            aria-label={t('previewImage', { name: item.name })}
            onClick={() => setPreview({ id: item.id, src, name: item.name })} /> : null}
          {onRemove ? <AttachmentActions>
            <AttachmentAction type="button" variant={isImage ? 'secondary' : 'ghost'}
              size={isImage ? 'icon' : 'icon-xs'} className={cn(isImage && 'rounded-full border')}
              aria-label={t('removeAttachment', { name: item.name })}
              onClick={() => { setPreview(null); onRemove(item.id); }}><X /></AttachmentAction>
          </AttachmentActions> : null}
        </Attachment>;
      })}
    </AttachmentGroup>
    <ImagePreview image={items.some((item) => item.id === preview?.id) ? preview : null} onClose={() => setPreview(null)} />
  </>;
}
