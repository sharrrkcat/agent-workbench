import { useEffect, useRef, useState } from 'react';
import type { ContextDetail } from '../../types/context';

export function useContextTokens(detail: ContextDetail | undefined) {
  const worker = useRef<Worker | null>(null);
  const requested = useRef(new Set<string>());
  const [cache, setCache] = useState<Record<string, Record<string, number | null>>>({});
  useEffect(() => {
    const instance = new Worker(new URL('./contextTokens.worker.ts', import.meta.url), { type: 'module' });
    worker.current = instance;
    instance.onmessage = (event: MessageEvent<{ key: string; counts: Record<string, number | null> }>) => {
      setCache((current) => ({ ...current, [event.data.key]: event.data.counts }));
    };
    instance.onerror = () => { instance.terminate(); worker.current = null; };
    return () => { instance.onmessage = null; instance.terminate(); worker.current = null; requested.current.clear(); };
  }, []);
  const key = detail ? `${detail.run_id}:${detail.step_id}` : undefined;
  useEffect(() => {
    if (!key || !detail || !worker.current || requested.current.has(key)) return;
    requested.current.add(key);
    worker.current.postMessage({ key, sources: detail.sources.filter((source) => source.attachment?.type !== 'image')
      .map(({ id, text }) => ({ id, text })) });
  }, [key, detail]);
  return key ? cache[key] : undefined;
}
