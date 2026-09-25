import { useTranslation } from 'react-i18next';
import { FieldGroup, Field, FieldLabel, FieldDescription } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select';
import type { ModelInput } from '../../../types/models';

export function ASRParameters({ parameters, onChange }: {
  parameters: ModelInput['parameters']; onChange: (value: ModelInput['parameters']) => void;
}) {
  const { t } = useTranslation('llm');
  const patch = (key: string, value: unknown) => onChange({ ...parameters, [key]: value });
  const formats = ['json', 'text', 'verbose_json'];
  return <FieldGroup className="@container-normal grid gap-4 sm:grid-cols-2">
    <p className="text-sm text-muted-foreground sm:col-span-2">{t('asr.defaultsHint')}</p>
    <Field>
      <FieldLabel>{t('asr.language')}</FieldLabel>
      <Input value={String(parameters.language ?? 'auto')} required pattern="auto|[a-z]{2,3}"
        onChange={(event) => patch('language', event.currentTarget.value)} />
      <FieldDescription>{t('asr.languageHint')}</FieldDescription>
    </Field>
    <Field>
      <FieldLabel>{t('params.temperature')}</FieldLabel>
      <Input type="number" min={0} max={1} step={0.1} required
        value={Number.isNaN(parameters.temperature) ? '' : Number(parameters.temperature ?? 0)}
        onChange={(event) => patch('temperature', event.currentTarget.value === '' ? Number.NaN : Number(event.currentTarget.value))} />
      <FieldDescription>{t('asr.temperatureHint')}</FieldDescription>
    </Field>
    <Field className="sm:col-span-2">
      <FieldLabel>{t('asr.prompt')}</FieldLabel>
      <Textarea rows={2} value={String(parameters.prompt ?? '')}
        onChange={(event) => patch('prompt', event.currentTarget.value)} />
      <FieldDescription>{t('asr.promptHint')}</FieldDescription>
    </Field>
    <Field className="sm:col-span-2">
      <FieldLabel>{t('asr.responseFormat')}</FieldLabel>
      <Select value={String(parameters.response_format ?? 'json')}
        items={formats.map((value) => ({ value, label: t('asr.formats.' + value) }))}
        onValueChange={(value) => { if (value !== null) patch('response_format', value); }}>
        <SelectTrigger><SelectValue /></SelectTrigger>
        <SelectContent>{formats.map((value) => <SelectItem key={value} value={value}>{t('asr.formats.' + value)}</SelectItem>)}</SelectContent>
      </Select>
      <FieldDescription>{t('asr.timestampsHint')}</FieldDescription>
    </Field>
  </FieldGroup>;
}
