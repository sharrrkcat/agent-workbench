import type { ReactNode } from 'react';

export function ToggleSwitch({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      className={`toggle-switch settings-toggle ${checked ? 'checked' : ''}`}
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onChange(!checked);
      }}
    >
      <span aria-hidden="true" />
      <small>{label || (checked ? 'Enabled' : 'Disabled')}</small>
    </button>
  );
}
