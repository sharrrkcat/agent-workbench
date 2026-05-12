export type StatusDotStatus = 'neutral' | 'good' | 'warning' | 'danger' | 'unknown';

export function StatusDot({ status = 'neutral', size = 'sm', className = '' }: { status?: StatusDotStatus; size?: 'sm' | 'md'; className?: string }) {
  return <span className={`status-dot ${size} ${status} ${className}`} aria-hidden="true" />;
}
