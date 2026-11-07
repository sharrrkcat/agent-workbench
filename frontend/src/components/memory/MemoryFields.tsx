import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { Field, FieldLabel } from '@/components/ui/field';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

export function MemorySelect({ label, value, options, onChange, disabled = false, compact = false }: {
  label: string; value: string; options: { value: string; label: string }[]; onChange: (value: string) => void; disabled?: boolean; compact?: boolean;
}) {
  const id = useId();
  return <Field className={compact ? 'memory-filter' : undefined}><FieldLabel htmlFor={id} className={compact ? 'sr-only' : undefined}>{label}</FieldLabel>
    <Select value={value} items={options} disabled={disabled} onValueChange={(next) => { if (next !== null && next !== value) onChange(next); }}>
      <SelectTrigger id={id}><SelectValue>{compact ? `${label}: ${options.find((option) => option.value === value)?.label ?? value}` : undefined}</SelectValue></SelectTrigger>
      <SelectContent><SelectGroup>{options.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectGroup></SelectContent>
    </Select>
  </Field>;
}

export function MemoryEnabledField({ value, onChange, hideLabel = false }: { value: boolean; onChange: (value: boolean) => void; hideLabel?: boolean }) {
  const { t } = useTranslation('memory'); const id = useId();
  return <Field orientation="horizontal"><Switch id={id} checked={value} onCheckedChange={onChange} />
    <FieldLabel htmlFor={id} className={hideLabel ? 'sr-only' : undefined}>{t('enabled')}</FieldLabel></Field>;
}
