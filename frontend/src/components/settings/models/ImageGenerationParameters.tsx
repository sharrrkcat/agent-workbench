import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { Field, FieldDescription, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import type { ModelInput } from '../../../types/models';

const choices = {
  quality: ['auto', 'low', 'medium', 'high', 'standard', 'hd'],
  style: ['natural', 'vivid'],
  response_format: ['url', 'b64_json'],
};

export function ImageGenerationParameters({ parameters, onChange }: {
  parameters: ModelInput['parameters']; onChange: (parameters: ModelInput['parameters']) => void;
}) {
  const { t } = useTranslation('llm');
  const patch = (key: string, value: unknown) => onChange({ ...parameters, [key]: value });
  return <FieldGroup className="@container-normal grid gap-4 sm:grid-cols-2">
    <Field>
      <FieldLabel>{t('imageGeneration.n')}</FieldLabel>
      <Input type="number" required min={1} max={10} step={1}
        value={Number.isNaN(parameters.n) ? '' : Number(parameters.n ?? 1)}
        onChange={(event) => patch('n', event.currentTarget.valueAsNumber)} />
    </Field>
    <Field>
      <FieldLabel>{t('imageGeneration.size')}</FieldLabel>
      <Input value={String(parameters.size ?? '')} maxLength={32} pattern="auto|[1-9][0-9]*x[1-9][0-9]*"
        placeholder={t('imageGeneration.providerDefault')}
        onChange={(event) => patch('size', event.currentTarget.value || null)} />
      <FieldDescription>{t('imageGeneration.sizeHelp')}</FieldDescription>
    </Field>
    {Object.entries(choices).map(([key, values]) => {
      const items = [{ value: 'provider-default', label: t('imageGeneration.providerDefault') },
        ...values.map((value) => ({ value, label: t(`imageGeneration.values.${value}`) }))];
      return <Field key={key}>
        <FieldLabel>{t('imageGeneration.' + key)}</FieldLabel>
        <Select value={String(parameters[key] ?? 'provider-default')} items={items}
          onValueChange={(value) => { if (value) patch(key, value === 'provider-default' ? null : value); }}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent><SelectGroup>
            {items.map((item) => <SelectItem value={item.value} key={item.value}>{item.label}</SelectItem>)}
          </SelectGroup></SelectContent>
        </Select>
      </Field>;
    })}
    <Field className="sm:col-span-2"><FieldDescription>{t('imageGeneration.optionsHelp')}</FieldDescription></Field>
  </FieldGroup>;
}
