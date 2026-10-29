import { useTranslation } from 'react-i18next';
import { CodeBlock, CodeBlockContent } from '@/components/ui/code-block';
import type { ToolResultPart } from '../../types/messages';

export function ToolResultBody({ part }: { part: ToolResultPart }) {
  const { t } = useTranslation('runs');
  return <>
    {part.error_message ? <CodeBlock size="sm" variant="destructive"><CodeBlockContent wrap className="max-h-64">
      {`${part.error_code ? `${part.error_code}: ` : ''}${part.error_message}`}
    </CodeBlockContent></CodeBlock> : null}
    {part.data !== undefined && part.data !== null ? <CodeBlock size="sm"><CodeBlockContent wrap className="max-h-64">
      {JSON.stringify(part.data, null, 2)}
    </CodeBlockContent></CodeBlock> : null}
    {part.truncated ? <span>{t('outputTruncated')}</span> : null}
  </>;
}
