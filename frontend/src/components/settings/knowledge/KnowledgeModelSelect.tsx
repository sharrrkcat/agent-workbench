import { useTranslation } from 'react-i18next';
import type { ModelProfile } from '../../../types/models';
import { Field } from '../resources/ResourceUI';

export function KnowledgeModelSelect({ kind, value, onChange, models, optional = false }: {
  kind: 'embedding' | 'reranker'; value: string | null; onChange: (id: string | null) => void; models: ModelProfile[]; optional?: boolean;
}) {
  const { t } = useTranslation('knowledge');
  const choices = models.filter((model) => model.kind === kind && (model.enabled || model.id === value));
  const missing = !!value && !choices.some((model) => model.id === value);
  return <Field label={t(kind === 'embedding' ? 'embeddingProfile' : 'rerankerProfile')}>
    <select aria-label={t(kind === 'embedding' ? 'embeddingProfile' : 'rerankerProfile')} required={!optional} value={value || ''} onChange={(event) => onChange(event.target.value || null)}>
      <option value="">{t('unconfigured')}</option>
      {missing ? <option value={value!} disabled>{t('missingModel')} ({value})</option> : null}
      {choices.map((model) => <option value={model.id} key={model.id} disabled={!model.enabled}>{model.name}{model.enabled ? '' : ` (${t('disabled')})`}</option>)}
    </select>
    {!choices.some((model) => model.enabled) ? <small>{t('noModels')}</small> : null}
  </Field>;
}
