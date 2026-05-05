import { X } from 'lucide-react';
import { SettingsPanel } from './SettingsPanel';

export function SettingsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;

  return (
    <div className="settings-overlay" role="presentation" onMouseDown={onClose}>
      <aside className="settings-drawer" role="dialog" aria-modal="true" aria-label="Settings" onMouseDown={(event) => event.stopPropagation()}>
        <div className="drawer-header">
          <div>
            <strong>Settings</strong>
            <span>Agents and capabilities</span>
          </div>
          <button className="icon-button" type="button" onClick={onClose} title="Close settings">
            <X size={16} />
          </button>
        </div>
        <SettingsPanel />
      </aside>
    </div>
  );
}
