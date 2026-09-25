import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Field, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { modelsApi } from '../../../api/models';
import type { LocalEmbeddingParameters, TextEmbeddingInspection } from '../../../types/models';

export function TextEmbeddingInspectionPanel({ modelRef, parameters, onChange }: {
  modelRef: string;
  parameters: LocalEmbeddingParameters;
  onChange: (parameters: LocalEmbeddingParameters) => void;
}) {
  const { t } = useTranslation('llm');
  const [information, setInformation] = useState<TextEmbeddingInspection | null>(null);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(true);
  const { query_prompt_name, document_prompt_name } = parameters;
  useEffect(() => {
    let cancelled = false;
    setPending(true);
    setError('');
    void modelsApi.inspectTextEmbedding(modelRef, { query_prompt_name, document_prompt_name }).then((value) => {
      if (!cancelled) setInformation(value);
    }).catch((reason) => {
      if (!cancelled) setError(String(reason.message));
    }).finally(() => {
      if (!cancelled) setPending(false);
    });
    return () => { cancelled = true; };
  }, [modelRef, query_prompt_name, document_prompt_name]);
  const display = (value: unknown) => value == null ? t('textEmbedding.pending')
    : typeof value === 'boolean' ? t(value ? 'enabled' : 'disabled') : String(value);
  const fields = information ? [
    ['modelType', information.model_type],
    ['dimensions', information.dimensions],
    ['textLimit', information.max_seq_length],
    ['similarity', information.similarity],
    ['normalize', information.normalize],
    ['pooling', information.pooling.map((item) => item.modes.join(' + ')).join(' → ') || null],
    ['includePrompt', information.pooling.length ? information.pooling.map((item) => display(item.include_prompt)).join(' / ') : null],
    ['pipeline', information.modules.map((item) => item.type.split('.').pop()).join(' → ') || null],
  ] as const : [];
  const choices = [{ value: '', label: t('textEmbedding.automatic') },
    ...Object.keys(information?.prompts ?? {}).map((name) => ({ value: name, label: name }))];
  return <FieldGroup role="group" aria-label={t('textEmbedding.information')}>
    <h3>{t('textEmbedding.information')}</h3>
    <p className="text-sm text-muted-foreground">{t('textEmbedding.informationHint')}</p>
    {pending ? <p role="status">{t('textEmbedding.inspecting')}</p> : null}
    {error ? <p role="status">{t('textEmbedding.inspectionFailed')} {error}</p> : null}
    {information ? <>
      <dl className="grid min-w-0 gap-3 text-sm sm:grid-cols-2">
        {fields.map(([key, value]) => <div key={key} className="min-w-0">
          <dt className="text-muted-foreground">{t('textEmbedding.fields.' + key)}</dt>
          <dd className="wrap-anywhere">{display(value)}</dd>
        </div>)}
      </dl>
      {!pending && !error ? <dl className="flex flex-col gap-3 text-sm">
        {(['query', 'document'] as const).map((purpose) => {
          const name = information[purpose + '_prompt_name' as keyof LocalEmbeddingParameters];
          return <div key={purpose}>
            <dt className="text-muted-foreground">{t('textEmbedding.' + purpose + 'Prompt')}</dt>
            <dd className="whitespace-pre-wrap wrap-anywhere">
              {name === null ? t('textEmbedding.noPrompt') : information.prompts[name]}
            </dd>
          </div>;
        })}
      </dl> : null}
      <Collapsible className="flex flex-col gap-3">
        <CollapsibleTrigger render={<Button type="button" variant="ghost" className="justify-start" />}>
          {t('textEmbedding.promptSettings')}
        </CollapsibleTrigger>
        <CollapsibleContent keepMounted>
          <FieldGroup className="grid gap-4 sm:grid-cols-2">
            {(['query_prompt_name', 'document_prompt_name'] as const).map((key) => <Field key={key}>
              <FieldLabel>{t('textEmbedding.' + (key === 'query_prompt_name' ? 'queryPrompt' : 'documentPrompt'))}</FieldLabel>
              <Select value={parameters[key] ?? ''} items={choices}
                onValueChange={(value) => onChange({ ...parameters, [key]: value || null })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent><SelectGroup>
                  {choices.map((choice) => <SelectItem key={choice.value} value={choice.value}>{choice.label}</SelectItem>)}
                </SelectGroup></SelectContent>
              </Select>
            </Field>)}
          </FieldGroup>
        </CollapsibleContent>
      </Collapsible>
      {!pending && !error && information.diagnostics.length ? <Alert>
        <AlertTitle>{t('textEmbedding.configurationNeeded')}</AlertTitle>
        <AlertDescription>
          <p>{t('textEmbedding.draftHint')}</p>
          <ul className="flex flex-col gap-1">
            {information.diagnostics.map((item, index) => <li key={index}>
              <code>{item.file}</code>: {t('textEmbedding.diagnostics.' + item.code)}
            </li>)}
          </ul>
        </AlertDescription>
      </Alert> : null}
    </> : null}
  </FieldGroup>;
}
