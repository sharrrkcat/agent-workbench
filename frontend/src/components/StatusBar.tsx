import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { CircleDot } from 'lucide-react';
import { Marker, MarkerContent, MarkerIcon } from '@/components/ui/marker';
import { settingsApi } from '../api/settings';

export function StatusBar() {
  const { t } = useTranslation('chat');
  const [status, setStatus] = useState('checking');
  useEffect(() => {
    let alive = true;
    void settingsApi
      .getHealthDetails()
      .then((value) => {
        if (alive)
          setStatus(
            String((value.llm as Record<string, unknown> | undefined)?.status || value.status || 'ready'),
          );
      })
      .catch(() => {
        if (alive) setStatus('offline');
      });
    return () => {
      alive = false;
    };
  }, []);
  return (
    <Marker render={<footer />} className="status-bar" role="status">
      <MarkerIcon>
        <CircleDot />
      </MarkerIcon>
      <MarkerContent>
        {t('service', { status: t('serviceStatus.' + status, { defaultValue: status }) })}
      </MarkerContent>
    </Marker>
  );
}
