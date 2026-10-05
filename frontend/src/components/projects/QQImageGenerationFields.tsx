import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { Field, FieldLabel, FieldDescription } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectGroup, SelectItem } from '@/components/ui/select';
import { useModelsStore } from '../../store/useModelsStore';
import type { QQBotInput } from '../../types/projects';
import { ModelSelect } from '../personas/ConfigurationFields';

const choices = {
  quality: ['auto', 'low', 'medium', 'high', 'standard', 'hd'],
  style: ['natural', 'vivid'],
} as const;

export function QQImageGenerationFields({ value, onChange }: {
  value: QQBotInput; onChange: (patch: Partial<QQBotInput>) => void;
}) {
  const { t } = useTranslation(['personas', 'llm']);
  const id = useId();
  const profiles = useModelsStore((s) => s.profiles);
  const providers = useModelsStore((s) => s.providers);
  const options = value.image_generation_options;
  return <>
    <Field><FieldLabel>{t('qq.imageGenerationModel')}</FieldLabel>
      <ModelSelect kind="image_generation" profiles={profiles.filter((p) => p.source?.type === 'provider').map((p) => ({
        ...p, enabled: p.enabled && providers.some((provider) => p.source?.type === 'provider' && provider.id === p.source.provider_profile_id && provider.enabled),
      }))} value={value.image_generation_model_profile_id} label={t('qq.imageGenerationModel')}
        inheritLabel={t('qq.noImageGeneration')} onChange={(model) => onChange({ image_generation_model_profile_id: model || null })} />
      <FieldDescription>{t('qq.imageGenerationHint')}</FieldDescription>
    </Field>
    {value.image_generation_model_profile_id ? <>
      <Field><FieldLabel htmlFor={id + '-size'}>{t('llm:imageGeneration.size')}</FieldLabel>
        <Input id={id + '-size'} value={options.size ?? ''} maxLength={32} pattern="auto|[1-9][0-9]*x[1-9][0-9]*"
          placeholder={t('qq.modelDefaults')} onChange={(event) => onChange({ image_generation_options: { ...options, size: event.target.value || null } })} />
        <FieldDescription>{t('llm:imageGeneration.sizeHelp')}</FieldDescription>
      </Field>
      {(Object.keys(choices) as (keyof typeof choices)[]).map((key) => {
        const items = [{ value: '', label: t('qq.modelDefaults') },
          ...choices[key].map((item) => ({ value: item, label: t(`llm:imageGeneration.values.${item}`) }))];
        return <Field key={key}><FieldLabel htmlFor={id + '-' + key}>{t(`llm:imageGeneration.${key}`)}</FieldLabel>
          <Select value={options[key] ?? ''} items={items} onValueChange={(item) => onChange({
            image_generation_options: { ...options, [key]: item || null },
          })}>
            <SelectTrigger id={id + '-' + key}><SelectValue /></SelectTrigger>
            <SelectContent><SelectGroup>{items.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}</SelectGroup></SelectContent>
          </Select>
        </Field>;
      })}
    </> : null}
  </>;
}
