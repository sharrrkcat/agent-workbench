import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

export function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="settings-panel">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

export function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="settings-toggle">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.currentTarget.checked)} />
      <span>{label}</span>
    </label>
  );
}

export function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <label className="settings-field">
      <span>{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(event) => onChange(Number(event.currentTarget.value))}
      />
    </label>
  );
}

export function TextArea({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="settings-field">
      <span>{label}</span>
      <textarea value={value} onChange={(event) => onChange(event.currentTarget.value)} rows={4} />
    </label>
  );
}

export function Loading() {
  const { t } = useTranslation('common');
  return <div className="settings-loading">{t('loading')}</div>;
}
