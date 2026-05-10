import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

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
  const { t } = useTranslation();
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
      <small>{label || (checked ? t('common:enabled') : t('common:disabled'))}</small>
    </button>
  );
}
