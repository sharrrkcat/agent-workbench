import { useTranslation } from 'react-i18next';
import { AppModal } from '../ui/AppModal';

export type PreviewImage = { src: string; name: string };

export function ImagePreview({ image, onClose }: { image: PreviewImage | null; onClose: () => void }) {
  const { t } = useTranslation('personas');
  return <AppModal open={!!image} title={image?.name || t('image')} closeLabel={t('close')} width="large" onClose={onClose}>
    {image ? <img className="image-preview" src={image.src} alt={image.name} /> : null}
  </AppModal>;
}
