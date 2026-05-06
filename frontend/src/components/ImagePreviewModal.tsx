import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import type { ImagePreview } from '../utils/images';

export function ImagePreviewModal({ image, onClose }: { image: ImagePreview | null; onClose: () => void }) {
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [image?.url]);

  useEffect(() => {
    if (!image) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [image, onClose]);

  if (!image) return null;

  const fallbackText = image.alt || image.title || image.caption || 'Image unavailable';

  return (
    <div className="image-preview-overlay" role="dialog" aria-modal="true" aria-label={image.title || image.alt || 'Image preview'} onClick={onClose}>
      <div className="image-preview-modal" onClick={(event) => event.stopPropagation()}>
        <button className="image-preview-close" type="button" onClick={onClose} title="Close image preview" aria-label="Close image preview">
          <X size={20} />
        </button>
        {image.title ? <div className="image-preview-title">{image.title}</div> : null}
        {failed ? <div className="image-preview-fallback">{fallbackText}</div> : <img src={image.url} alt={image.alt || image.title || image.caption || ''} onError={() => setFailed(true)} />}
        {image.caption ? <div className="image-preview-caption">{image.caption}</div> : null}
      </div>
    </div>
  );
}
