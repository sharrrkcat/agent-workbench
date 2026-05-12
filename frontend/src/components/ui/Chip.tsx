import type { ReactNode } from 'react';

export type ChipTone = 'neutral' | 'active' | 'warning' | 'danger';

export function Chip({ tone = 'neutral', children, className = '' }: { tone?: ChipTone; children: ReactNode; className?: string }) {
  return <span className={`status-chip ${tone} ${className}`}>{children}</span>;
}

export const StatusChip = Chip;
