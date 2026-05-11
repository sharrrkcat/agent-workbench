import { useEffect, useState } from 'react';

export function usePopoverPresence(open: boolean, durationMs = 150): boolean {
  const [rendered, setRendered] = useState(open);

  useEffect(() => {
    if (open) {
      setRendered(true);
      return;
    }
    const timeoutId = window.setTimeout(() => setRendered(false), durationMs);
    return () => window.clearTimeout(timeoutId);
  }, [durationMs, open]);

  return rendered;
}
