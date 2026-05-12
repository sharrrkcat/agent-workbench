import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

export function ToggleSwitch({
  checked,
  onChange,
  label,
  showLabel = true,
  size = 'default',
  disabled = false,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: ReactNode;
  showLabel?: boolean;
  size?: 'default' | 'small';
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const statusLabel = label || (checked ? t('common:enabled') : t('common:disabled'));
  return (
    <button
      className={`ui-toggle settings-toggle ${size === 'small' ? 'small' : ''} ${checked ? 'checked' : ''}`}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={typeof statusLabel === 'string' ? statusLabel : undefined}
      disabled={disabled}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onChange(!checked);
      }}
    >
      <span aria-hidden="true" />
      {showLabel ? <small>{statusLabel}</small> : null}
    </button>
  );
}

export function MiniToggle(props: Omit<Parameters<typeof ToggleSwitch>[0], 'size' | 'showLabel'> & { showLabel?: boolean }) {
  return <ToggleSwitch {...props} size="small" showLabel={props.showLabel ?? false} />;
}
