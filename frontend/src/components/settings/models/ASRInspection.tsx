import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { FieldGroup, FieldLegend, FieldSet } from '@/components/ui/field';
import { modelsApi } from '../../../api/models';
import type { ASRInspection } from '../../../types/models';

export function ASRInspectionPanel({ modelRef }: { modelRef: string }) {
  const { t } = useTranslation('llm');
  const [result, setResult] = useState<{ ref: string; information?: ASRInspection; error?: string } | null>(null);
  useEffect(() => {
    let cancelled = false;
    setResult(null);
    if (modelRef.trim()) void modelsApi.inspectASR(modelRef).then((information) => {
      if (!cancelled) setResult({ ref: modelRef, information });
    }).catch((error) => {
      if (!cancelled) setResult({ ref: modelRef, error: String(error.message) });
    });
    return () => { cancelled = true; };
  }, [modelRef]);
  const current = result?.ref === modelRef ? result : null;
  const information = current?.information;
  const fields = information ? [
    ['architecture', information.architecture === 'whisper' ? 'Whisper' : null],
    ['processor', information.processor], ['sampleRate', information.sample_rate],
    ['features', information.feature_size], ['window', information.window_seconds],
    ['timestamps', t(information.segment_timestamps ? 'asr.supported' : 'asr.unavailable')],
  ] as const : [];
  return <FieldSet aria-label={t('asr.information')}>
    <FieldLegend>{t('asr.information')}</FieldLegend>
    <FieldGroup>
      <p className="text-sm text-muted-foreground">{t('asr.informationHint')}</p>
      {modelRef.trim() && !current ? <p role="status">{t('asr.inspecting')}</p> : null}
      {current?.error ? <p role="status">{t('asr.inspectionFailed')} {current.error}</p> : null}
      {information ? <>
        <dl className="grid min-w-0 gap-3 text-sm sm:grid-cols-2">
          {fields.map(([key, value]) => <div key={key} className="min-w-0">
            <dt className="text-muted-foreground">{t('asr.fields.' + key)}</dt>
            <dd className="wrap-anywhere">{value ?? t('asr.undetermined')}</dd>
          </div>)}
          <div className="min-w-0 sm:col-span-2">
            <dt className="text-muted-foreground">{t('asr.fields.languages')}</dt>
            <dd className="wrap-anywhere">{information.languages.join(', ') || t('asr.undetermined')}</dd>
          </div>
        </dl>
        {information.diagnostics.length ? <Alert>
          <AlertTitle>{t('asr.configurationNeeded')}</AlertTitle>
          <AlertDescription>
            <p>{t('asr.draftHint')}</p>
            <ul className="flex flex-col gap-1">{information.diagnostics.map((item, index) => <li key={index}>
              <code>{item.file}</code>: {t('asr.diagnostics.' + item.code)}
            </li>)}</ul>
          </AlertDescription>
        </Alert> : null}
      </> : null}
    </FieldGroup>
  </FieldSet>;
}
