import { useTranslation } from 'react-i18next';
import { FieldGroup, Field, FieldLabel, FieldDescription } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import type { ModelInput } from '../../../types/models';
import { processorDefaults } from './profileDefaults';

export function ProcessorParameters({ parameters, onChange }: {
  parameters: ModelInput['parameters']; onChange: (value: ModelInput['parameters']) => void;
}) {
  const { t } = useTranslation('llm');
  const values = { ...processorDefaults, ...parameters };
  const patch = (key: string, value: unknown) => onChange({ ...values, [key]: value });
  return <FieldGroup className="@container-normal grid gap-4 sm:grid-cols-2">
    <Field className="sm:col-span-2">
      <FieldLabel>{t('params.task')}</FieldLabel>
      <Input value={t('processor.task')} readOnly />
      <FieldDescription>{t('processor.defaultsHint')}</FieldDescription>
    </Field>
    {([
      ['style', ['natural', 'cinematic', 'default', '3', '4', '5', '6']],
      ['preset', ['0', '1', '2', '3']],
      ['channel_order', ['auto', 'RGBA', 'BGRA']],
    ] as const).map(([key, choices]) => <Field key={key} className="sm:col-span-2">
      <FieldLabel>{t('processor.' + key)}</FieldLabel>
      <ToggleGroup value={[String(values[key])]} variant="outline" className="max-w-full flex-wrap"
        aria-label={t('processor.' + key)} onValueChange={(next) => {
          if (next.length) patch(key, key === 'preset' ? Number(next[0]) : next[0]);
        }}>
        {choices.map((choice) => <ToggleGroupItem value={choice} key={choice}>
          {key === 'style' ? t('processor.styles.' + choice) : choice === 'auto' ? t('processor.auto') : choice}
        </ToggleGroupItem>)}
      </ToggleGroup>
    </Field>)}
    {(['intensity', 'tone', 'structure', 'skin'] as const).map((key) => <Field key={key}>
      <FieldLabel>{t('processor.' + key)}</FieldLabel>
      <Input type="number" min={key === 'skin' ? -1 : 0} max={2} step="any" required
        value={Number.isNaN(values[key]) ? '' : Number(values[key])}
        onChange={(event) => patch(key, event.currentTarget.value === '' ? Number.NaN : Number(event.currentTarget.value))} />
    </Field>)}
    <Field orientation="horizontal">
      <Switch checked={values.auto_mask === true} onCheckedChange={(value) => patch('auto_mask', value)} />
      <FieldLabel>{t('processor.auto_mask')}</FieldLabel>
    </Field>
  </FieldGroup>;
}
