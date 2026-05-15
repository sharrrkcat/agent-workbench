import type { ReactNode } from 'react';

export type ChipTone = 'neutral' | 'active' | 'warning' | 'danger';

export function Chip({ tone = 'neutral', children, className = '', title }: { tone?: ChipTone; children: ReactNode; className?: string; title?: string }) {
  return <span className={`status-chip ${tone} ${className}`} title={title}>{children}</span>;
}

export const StatusChip = Chip;
