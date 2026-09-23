import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { useTranslation } from 'react-i18next';

export type PreviewImage = { src: string; name: string };

export function ImagePreview({ image, onClose }: { image: PreviewImage | null; onClose: () => void }) {
  const { t } = useTranslation('personas');
  return (
    <Dialog
      open={!!image}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{image?.name || t('image')}</DialogTitle>
        </DialogHeader>
        <div className="min-h-0 overflow-y-auto overscroll-contain">
          {image ? (
            <img
              className="image-preview mx-auto max-h-[calc(100dvh-8rem)] w-full max-w-full object-contain"
              src={image.src}
              alt={image.name}
            />
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}
