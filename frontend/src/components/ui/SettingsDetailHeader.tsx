import type { ReactNode } from 'react';

export function SettingsDetailHeader({
  icon,
  title,
  subtitle,
  actions,
}: {
  icon: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="settings-detail-header">
      <div className="settings-detail-title">
        <div className="settings-detail-avatar">{icon}</div>
        <div>
          <h2>{title}</h2>
          {subtitle ? <p>{subtitle}</p> : null}
        </div>
      </div>
      <div className="settings-detail-actions">{actions}</div>
    </header>
  );
}
