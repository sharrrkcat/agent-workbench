import { useEffect, useState } from 'react';
import { settingsApi } from '../api/settings';

export function StatusBar() {
  const [status, setStatus] = useState('');
  useEffect(() => { let alive = true; void settingsApi.getHealthDetails().then((value) => { if (alive) setStatus(String((value.llm as Record<string, unknown> | undefined)?.status || value.status || 'ready')); }).catch(() => { if (alive) setStatus('offline'); }); return () => { alive = false; }; }, []);
  return <footer className="status-bar"><span className={`status-dot ${status === 'ok' ? 'ok' : status === 'offline' ? 'bad' : ''}`} /> <span>Service: {status || 'checking…'}</span></footer>;
}
