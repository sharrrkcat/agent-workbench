import { useEffect, useState } from 'react';
import { api } from '../api/client';

export function StatusBar() {
  const [status, setStatus] = useState('');
  useEffect(() => { let alive = true; void api.getHealthDetails().then((value) => { if (alive) setStatus(String((value.llm as Record<string, unknown> | undefined)?.status || value.status || 'ready')); }).catch(() => { if (alive) setStatus('offline'); }); return () => { alive = false; }; }, []);
  return <footer className="status-bar"><span className={`status-dot ${status === 'ok' ? 'ok' : status === 'offline' ? 'bad' : ''}`} /> <span>Service: {status || 'checking…'}</span></footer>;
}
