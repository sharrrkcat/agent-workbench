import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { Button } from '@/components/ui/button';
import { CodeBlock, CodeBlockContent } from '@/components/ui/code-block';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Marker, MarkerContent } from '@/components/ui/marker';
import { useTranslation } from 'react-i18next';
import { Children, type ComponentProps, type ReactElement } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { MessagePart } from '../../types/messages';
import { API_BASE_URL, resolveAttachmentUrlFromBase } from '../../api/url';
import { ToolResultBody } from './ToolResultBody';
import { imageErrorKey } from './messageContent';
import { remarkWebCitations, type WebSourceMap } from './webSources';
import { PlainWebCitations, WebCitation } from './WebCitation';

export function MessageParts({ parts, compact = false, webSources }: { parts: MessagePart[]; compact?: boolean; webSources?: WebSourceMap }) {
  return (
    <div className="message-parts">
      {parts.map((part) => (
        <Part key={part.id} part={part} compact={compact} webSources={webSources} />
      ))}
    </div>
  );
}

function Part({ part, compact, webSources }: { part: MessagePart; compact: boolean; webSources?: WebSourceMap }) {
  const { t } = useTranslation('runs');
  if (part.type === 'text' || part.type === 'reasoning')
    return part.type === 'text' && part.format === 'plain' ? (
      <p className="part-text">{webSources?.size ? <PlainWebCitations text={part.text} sources={webSources} /> : part.text}</p>
    ) : (
      <div className="part-markdown">
        <ReactMarkdown
          remarkPlugins={[remarkGfm, [remarkWebCitations, webSources]]}
          components={{
            a: ({ node, children, ...props }) => {
              const id = node?.properties['data-web-source'];
              const source = typeof id === 'string' ? webSources?.get(id) : undefined;
              return source ? <WebCitation source={source} /> : <a {...props}>{children}</a>;
            },
            pre: ({ children }) => {
              const code = Children.only(children) as ReactElement<ComponentProps<'code'>>;
              return <CodeBlock size={compact ? 'sm' : 'default'}>
                <CodeBlockContent className="max-h-80" codeClassName={code.props.className}>{code.props.children}</CodeBlockContent>
              </CodeBlock>;
            },
            table: ({ children }) => (
              <div className="markdown-table">
                <table>{children}</table>
              </div>
            ),
          }}
        >
          {part.text}
        </ReactMarkdown>
      </div>
    );
  if (part.type === 'json') return <CodeBlock size={compact ? 'sm' : 'default'}><CodeBlockContent wrap className="max-h-80">{JSON.stringify(part.data, null, 2)}</CodeBlockContent></CodeBlock>;
  if (part.type === 'tool_call')
    return (
      <Collapsible className="part-tool" defaultOpen={true}>
        <CollapsibleTrigger render={<Button type="button" variant="ghost" className="justify-start" />}>
          {t('toolCall')}· {part.tool_name}
        </CollapsibleTrigger>
        <CollapsibleContent keepMounted>
          <CodeBlock size="sm"><CodeBlockContent wrap className="max-h-64">{JSON.stringify(part.arguments, null, 2)}</CodeBlockContent></CodeBlock>
        </CollapsibleContent>
      </Collapsible>
    );
  if (part.type === 'tool_result')
    return (
      <Collapsible className={`part-tool tool-${part.status}`} defaultOpen={true}>
        <CollapsibleTrigger render={<Button type="button" variant="ghost" className="justify-start" />}>
          {part.tool_name}· {t(`toolStatus.${part.status}`)}
        </CollapsibleTrigger>
        <CollapsibleContent keepMounted>
          <ToolResultBody part={part} />
        </CollapsibleContent>
      </Collapsible>
    );
  if (part.type === 'file')
    return (
      <CodeBlock size={compact ? 'sm' : 'default'}><CodeBlockContent className="max-h-80">
        {part.content || part.filename || part.attachment_id || t('renderers:file')}
      </CodeBlockContent></CodeBlock>
    );
  if (part.type === 'image') {
    const url =
      part.url ||
      (part.attachment_id
        ? resolveAttachmentUrlFromBase(API_BASE_URL, `local://attachments/${part.attachment_id}`)
        : '');
    return url ? (
      <figure className="part-image">
        <img src={url} alt={part.alt || part.title || ''} />
        <figcaption>{part.caption}</figcaption>
      </figure>
    ) : null;
  }
  if (part.type === 'media_group')
    return (
      <div className="part-gallery">
        {part.items.map((item, index) => {
          const url =
            item.url ||
            (item.attachment_id
              ? resolveAttachmentUrlFromBase(API_BASE_URL, `local://attachments/${item.attachment_id}`)
              : '');
          return url ? <img key={`${url}-${index}`} src={url} alt={item.alt || ''} /> : null;
        })}
      </div>
    );
  if (part.type === 'audio') return <audio controls src={part.url} />;
  if (part.type === 'video') return <video controls src={part.url} poster={part.poster_url} />;
  if (part.type === 'error')
    return (
      <Alert className="part-error" variant="destructive">
        <AlertDescription>
          {part.code ? `${part.code}: ` : ''}
          {imageErrorKey(part.code, part.message) ? t(imageErrorKey(part.code, part.message)!) : part.message}
        </AlertDescription>
      </Alert>
    );
  return (
    <Marker className="part-notice">
      <MarkerContent>{part.text}</MarkerContent>
    </Marker>
  );
}
