import { useTranslation } from 'react-i18next';
import type { ToolResultPart } from '../../types/messages';

export function ToolResultBody({ part }: { part: ToolResultPart }) {
  const { t } = useTranslation('runs');
  return <>
    {part.error_message ? <p className="part-error">{part.error_code ? `${part.error_code}: ` : ''}{part.error_message}</p> : null}
    {part.data !== undefined && part.data !== null ? <pre className="part-json">{JSON.stringify(part.data, null, 2)}</pre> : null}
    {part.truncated ? <small>{t('outputTruncated')}</small> : null}
  </>;
}
