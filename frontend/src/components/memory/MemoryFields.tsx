import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { Field, FieldDescription, FieldLabel } from '@/components/ui/field';
import { Switch } from '@/components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

export function MemorySelect({ label, value, options, onChange, disabled = false }: {
  label: string; value: string; options: { value: string; label: string }[]; onChange: (value: string) => void; disabled?: boolean;
}) {
  const id = useId();
  return <Field><FieldLabel htmlFor={id}>{label}</FieldLabel>
    <Select value={value} items={options} disabled={disabled} onValueChange={(next) => { if (next !== null) onChange(next); }}>
      <SelectTrigger id={id}><SelectValue /></SelectTrigger>
      <SelectContent><SelectGroup>{options.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectGroup></SelectContent>
    </Select>
  </Field>;
}

export function MemoryReadField({ value, onChange, hideLabel = false }: { value: boolean; onChange: (value: boolean) => void; hideLabel?: boolean }) {
  const { t } = useTranslation('memory'); const id = useId();
  return <Field orientation="horizontal"><Switch id={id} checked={value} onCheckedChange={onChange} />
    <FieldLabel htmlFor={id} className={hideLabel ? 'sr-only' : undefined}>{t('readEnabled')}</FieldLabel></Field>;
}

export function MemoryLearningField({ value, harness, onChange, hideLabel = false }: {
  value: 'manual' | 'automatic'; harness: boolean; onChange: (value: 'manual' | 'automatic') => void; hideLabel?: boolean;
}) {
  const { t } = useTranslation('memory'); const id = useId();
  return <Field><FieldLabel id={id} className={hideLabel ? 'sr-only' : undefined}>{t('learning')}</FieldLabel>
    <ToggleGroup variant="outline" value={[value]} onValueChange={(next) => { if (next[0]) onChange(next[0] as typeof value); }} aria-labelledby={id}>
      <ToggleGroupItem value="manual">{t('manual')}</ToggleGroupItem>
      <ToggleGroupItem value="automatic">{t('automatic')}</ToggleGroupItem>
    </ToggleGroup>
    {value === 'automatic' && !harness ? <FieldDescription>{t('harnessRequired')}</FieldDescription> : null}
  </Field>;
}
