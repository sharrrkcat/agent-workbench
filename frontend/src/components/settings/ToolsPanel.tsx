import { Fragment, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { CodeBlock, CodeBlockContent } from '@/components/ui/code-block';
import { Item, ItemContent, ItemDescription, ItemGroup, ItemTitle } from '@/components/ui/item';
import { LoadingStatus } from '@/components/ui/loading-status';
import { Separator } from '@/components/ui/separator';
import { toolsApi } from '../../api/tools';
import type { HarnessTool } from '../../types/tools';
import { errorText, Feedback } from './resources/ResourceUI';

export function ToolsPanel() {
  const { t } = useTranslation('settings');
  const [tools, setTools] = useState<HarnessTool[] | null>(null);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let live = true;
    setTools(null);
    setError('');
    void toolsApi.listTools().then((catalog) => {
      if (live) setTools(catalog);
    }).catch((reason) => { if (live) setError(errorText(reason)); });
    return () => { live = false; };
  }, [reload]);

  return (
    <section className="settings-panel" aria-label={t('toolCatalog')}>
      {error ? (
        <>
          <Feedback error={error} />
          <Button type="button" variant="outline" onClick={() => setReload((value) => value + 1)}>
            {t('resources.refresh')}
          </Button>
        </>
      ) : tools === null ? <LoadingStatus /> : (
        (['general', 'qqbot'] as const).map((scope, index) => (
          <Fragment key={scope}>
            {index > 0 ? <Separator /> : null}
            <section className="flex min-w-0 flex-col gap-3" aria-labelledby={`tools-${scope}`}>
              <h2 id={`tools-${scope}`}>{t('toolGroups.' + scope)}</h2>
              <ItemGroup>
                {tools.filter((tool) => tool.scope === scope).map((tool) => (
                  <Item key={tool.name} role="listitem" className="min-w-0 px-0" data-tool-name={tool.name}>
                    <ItemContent className="min-w-0">
                      <ItemTitle>{tool.name}</ItemTitle>
                      <ItemDescription className="line-clamp-none">
                        {t('toolDescriptions.' + tool.name, { defaultValue: tool.description })}
                      </ItemDescription>
                      <Collapsible>
                        <CollapsibleTrigger render={<Button type="button" variant="ghost" size="sm" />}>
                          {t('toolSchema')}
                        </CollapsibleTrigger>
                        <CollapsibleContent>
                          <CodeBlock size="sm">
                            <CodeBlockContent className="max-h-80" aria-label={`${tool.name} ${t('toolSchema')}`}>
                              {JSON.stringify(tool.parameters, null, 2)}
                            </CodeBlockContent>
                          </CodeBlock>
                        </CollapsibleContent>
                      </Collapsible>
                    </ItemContent>
                  </Item>
                ))}
              </ItemGroup>
            </section>
          </Fragment>
        ))
      )}
    </section>
  );
}
