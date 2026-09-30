import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

export function LoadingStatus() {
  const { t } = useTranslation('common');
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setVisible(true), 200);
    return () => clearTimeout(timer);
  }, []);

  return visible ? (
    <p data-slot="loading-status" className="px-2 py-1 text-xs text-muted-foreground" role="status">
      {t('loading')}
    </p>
  ) : null;
}
