import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Marker, MarkerContent } from '@/components/ui/marker';
import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { MessagePart } from '../../types/messages';
import { API_BASE_URL, resolveAttachmentUrlFromBase } from '../../api/url';
import { ToolResultBody } from './ToolResultBody';
import { imageErrorKey } from './messageContent';

export function MessageParts({ parts }: { parts: MessagePart[] }) {
  return (
    <div className="message-parts">
      {parts.map((part) => (
        <Part key={part.id} part={part} />
      ))}
    </div>
  );
}

function Part({ part }: { part: MessagePart }) {
  const { t } = useTranslation('runs');
  if (part.type === 'text' || part.type === 'reasoning')
    return part.type === 'text' && part.format === 'plain' ? (
      <p className="part-text">{part.text}</p>
    ) : (
      <div className="part-markdown">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
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
  if (part.type === 'json') return <pre className="part-json">{JSON.stringify(part.data, null, 2)}</pre>;
  if (part.type === 'tool_call')
    return (
      <Collapsible className="part-tool" defaultOpen={true}>
        <CollapsibleTrigger render={<Button type="button" variant="ghost" className="justify-start" />}>
          {t('toolCall')}· {part.tool_name}
        </CollapsibleTrigger>
        <CollapsibleContent keepMounted>
          <pre className="part-json">{JSON.stringify(part.arguments, null, 2)}</pre>
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
      <pre className="part-file">
        {part.content || part.filename || part.attachment_id || t('renderers:file')}
      </pre>
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
