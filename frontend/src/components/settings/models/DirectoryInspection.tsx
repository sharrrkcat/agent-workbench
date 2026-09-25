import { useTranslation } from 'react-i18next';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { FieldGroup, FieldLegend, FieldSet } from '@/components/ui/field';
import type { DirectoryInspection } from '../../../types/models';

export function DirectoryInspectionPanel({ information, error }: { information?: DirectoryInspection; error?: string }) {
  const { t } = useTranslation('llm');
  const fields: [string, string | null][] = information ? [
    ['engine', information.engine ? t('engines.' + information.engine) : null],
    ['architecture', information.architecture],
  ] : [];
  if (information?.kind === 'vision') fields.push(['backbone', information.backbone]);
  if (information?.kind === 'llm' && information.engine === 'llama-server') {
    fields.push(['mainModel', information.main_model_ref], ['projector', information.mmproj_ref]);
  }
  return <FieldSet aria-label={t('directory.information')}>
    <FieldLegend>{t('directory.information')}</FieldLegend>
    <FieldGroup>
      <p className="text-sm text-muted-foreground">{t('directory.informationHint')}</p>
      {!information && !error ? <p role="status">{t('directory.inspecting')}</p> : null}
      {error ? <p role="status">{t('directory.failed')} {error}</p> : null}
      {information ? <>
        <dl className="grid min-w-0 gap-3 text-sm sm:grid-cols-2">
          {fields.map(([key, value]) => <div key={key} className="min-w-0">
            <dt className="text-muted-foreground">{t('directory.fields.' + key)}</dt>
            <dd className="wrap-anywhere">{value ?? t('directory.undetermined')}</dd>
          </div>)}
        </dl>
        {information.diagnostics.length ? <Alert>
          <AlertTitle>{t('directory.configurationNeeded')}</AlertTitle>
          <AlertDescription>
            <p>{t('directory.draftHint')}</p>
            <ul className="flex flex-col gap-1">{information.diagnostics.map((item, index) => <li key={index}>
              {t(item.blocking ? 'directory.blocking' : 'directory.warning')} — <code>{item.file}</code>: {t('directory.diagnostics.' + item.code)}
            </li>)}</ul>
          </AlertDescription>
        </Alert> : null}
      </> : null}
    </FieldGroup>
  </FieldSet>;
}
