import type { ReactNode } from 'react';

export function InlineStatus({ tone = 'neutral', children, className = '' }: { tone?: 'neutral' | 'saving' | 'saved' | 'failed' | 'warning'; children: ReactNode; className?: string }) {
  return <span className={`inline-status ${tone} ${className}`}>{children}</span>;
}
