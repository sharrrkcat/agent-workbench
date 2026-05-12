import type { ReactNode } from 'react';

export function EmptyStateRow({ message, action, className = '' }: { message: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={`settings-empty-state compact empty-state-row ${className}`}>
      <span>{message}</span>
      {action ? <div className="empty-state-row-action">{action}</div> : null}
    </div>
  );
}
