import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { FieldGroup, FieldLegend, FieldSet } from '@/components/ui/field';
import { modelsApi } from '../../../api/models';
import type { RerankerInspection } from '../../../types/models';

export function RerankerInspectionPanel({ modelRef }: { modelRef: string }) {
  const { t } = useTranslation('llm');
  const [result, setResult] = useState<{ ref: string; information?: RerankerInspection; error?: string } | null>(null);
  useEffect(() => {
    let cancelled = false;
    setResult(null);
    if (modelRef.trim()) void modelsApi.inspectReranker(modelRef).then((information) => {
      if (!cancelled) setResult({ ref: modelRef, information });
    }).catch((error) => {
      if (!cancelled) setResult({ ref: modelRef, error: String(error.message) });
    });
    return () => { cancelled = true; };
  }, [modelRef]);
  const current = result?.ref === modelRef ? result : null;
  const information = current?.information;
  const fields = information ? [
    ['architecture', information.architecture === 'cross-encoder' ? 'Cross-Encoder' : null],
    ['modelType', information.model_type],
    ['textLimit', information.max_seq_length],
    ['scoring', information.scoring.method ? t('reranker.methods.' + information.scoring.method) : null],
    ['activation', information.scoring.activation?.split('.').pop()],
    ['pipeline', information.modules.map((item) => item.type.split('.').pop()).join(' → ') || null],
  ] as const : [];
  return <FieldSet aria-label={t('reranker.information')}>
    <FieldLegend>{t('reranker.information')}</FieldLegend>
    <FieldGroup>
      <p className="text-sm text-muted-foreground">{t('reranker.informationHint')}</p>
      {modelRef.trim() && !current ? <p role="status">{t('reranker.inspecting')}</p> : null}
      {current?.error ? <p role="status">{t('reranker.inspectionFailed')} {current.error}</p> : null}
      {information ? <>
        <dl className="grid min-w-0 gap-3 text-sm sm:grid-cols-2">
          {fields.map(([key, value]) => <div key={key} className="min-w-0">
            <dt className="text-muted-foreground">{t('reranker.fields.' + key)}</dt>
            <dd className="wrap-anywhere">{value ?? t('reranker.undetermined')}</dd>
          </div>)}
        </dl>
        {information.diagnostics.length ? <Alert>
          <AlertTitle>{t('reranker.configurationNeeded')}</AlertTitle>
          <AlertDescription>
            <p>{t('reranker.draftHint')}</p>
            <ul className="flex flex-col gap-1">
              {information.diagnostics.map((item, index) => <li key={index}>
                <code>{item.file}</code>: {t('reranker.diagnostics.' + item.code)}
              </li>)}
            </ul>
          </AlertDescription>
        </Alert> : null}
      </> : null}
    </FieldGroup>
  </FieldSet>;
}
