import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectGroup,
  SelectItem,
} from '@/components/ui/select';
import { Field, FieldLabel } from '@/components/ui/field';
import { useTranslation } from 'react-i18next';
import type { ModelProfile } from '../../../types/models';
import { useSettingsView } from '../SettingsView';

export function KnowledgeModelSelect({
  kind,
  value,
  onChange,
  models,
  optional = false,
}: {
  kind: 'embedding' | 'reranker';
  value: string | null;
  onChange: (id: string | null) => void;
  models: ModelProfile[];
  optional?: boolean;
}) {
  const { t } = useTranslation('knowledge');
  const activeView = useSettingsView();
  const choices = models.filter((model) => model.kind === kind && (model.enabled || model.id === value));
  const missing = !!value && !choices.some((model) => model.id === value);
  return (
    <Field>
      <FieldLabel>{t(kind === 'embedding' ? 'embeddingProfile' : 'rerankerProfile')}</FieldLabel>
      <Select
        key={String(activeView)}
        required={!optional}
        value={value || ''}
        onValueChange={(selected) => onChange((selected ?? '') || null)}
        items={[
          { value: '', label: t('unconfigured') },
          ...(missing
            ? [
                {
                  value: value!,
                  label: (
                    <>
                      {t('missingModel')}({value})
                    </>
                  ),
                },
              ]
            : []),
          ...choices.map((model) => ({
            value: model.id,
            label: (
              <>
                {model.name}
                {model.enabled ? '' : ` (${t('disabled')})`}
              </>
            ),
          })),
        ]}
      >
        <SelectTrigger aria-label={t(kind === 'embedding' ? 'embeddingProfile' : 'rerankerProfile')}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectGroup>
            <SelectItem value="">{t('unconfigured')}</SelectItem>
            {missing ? (
              <SelectItem value={value!} disabled>
                {t('missingModel')}({value})
              </SelectItem>
            ) : null}
            {choices.map((model) => (
              <SelectItem value={model.id} key={model.id} disabled={!model.enabled}>
                {model.name}
                {model.enabled ? '' : ` (${t('disabled')})`}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
      {!choices.some((model) => model.enabled) ? <small>{t('noModels')}</small> : null}
    </Field>
  );
}
