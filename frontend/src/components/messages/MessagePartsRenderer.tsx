import type { ReactNode } from 'react';
import type { ActionFormBlock, CommandButtonsBlock, FileContentPayload, ImagePayload, Message, MessagePart } from '../../types';
import { CommandButtonsPartRenderer } from './parts/CommandButtonsPartRenderer';
import { ErrorPartRenderer } from './parts/ErrorPartRenderer';
import { FilePartRenderer } from './parts/FilePartRenderer';
import { FormPartRenderer } from './parts/FormPartRenderer';
import { ImagePartRenderer } from './parts/ImagePartRenderer';
import { JsonPartRenderer } from './parts/JsonPartRenderer';
import { MediaGroupPartRenderer } from './parts/MediaGroupPartRenderer';
import { NoticePartRenderer } from './parts/NoticePartRenderer';
import { TextPartRenderer } from './parts/TextPartRenderer';

export function MessagePartsRenderer({
  parts,
  message,
  renderMarkdown,
  renderPlainText,
  renderJson,
  renderFile,
  renderImage,
  renderImageGallery,
  renderForm,
  renderCommandButtons,
}: {
  parts: MessagePart[] | undefined;
  message: Message;
  renderMarkdown: (text: string) => ReactNode;
  renderPlainText: (text: string) => ReactNode;
  renderJson: (data: unknown) => ReactNode;
  renderFile: (payload: FileContentPayload) => ReactNode;
  renderImage: (image: ImagePayload | null) => ReactNode;
  renderImageGallery: (images: ImagePayload[]) => ReactNode;
  renderForm: (form: ActionFormBlock, blockIndex: number) => ReactNode;
  renderCommandButtons: (block: CommandButtonsBlock) => ReactNode;
}) {
  const renderableParts = Array.isArray(parts) ? parts.filter(isRenderableMessagePart) : [];
  if (!renderableParts.length) return null;

  return (
    <div className="message-content parts-content" data-message-id={message.message_id}>
      {renderableParts.map((part, index) => {
        const key = stablePartKey(part, index);
        try {
          switch (part.type) {
            case 'text':
              return <TextPartRenderer key={key} part={part} renderMarkdown={renderMarkdown} renderPlainText={renderPlainText} />;
            case 'json':
              return <JsonPartRenderer key={key} part={part} renderJson={renderJson} />;
            case 'file':
              return <FilePartRenderer key={key} part={part} renderFile={renderFile} renderPlainText={renderPlainText} />;
            case 'image':
              return <ImagePartRenderer key={key} part={part} renderImage={renderImage} renderPlainText={renderPlainText} />;
            case 'media_group':
              return <MediaGroupPartRenderer key={key} part={part} renderImageGallery={renderImageGallery} renderPlainText={renderPlainText} />;
            case 'form':
              return <FormPartRenderer key={key} part={part} partIndex={index} renderForm={renderForm} />;
            case 'command_buttons':
              return <CommandButtonsPartRenderer key={key} part={part} renderCommandButtons={renderCommandButtons} />;
            case 'notice':
              return <NoticePartRenderer key={key} part={part} />;
            case 'error':
              return <ErrorPartRenderer key={key} part={part} />;
            default:
              return <div key={key} className="message-content message-part-notice warning">{String((part as { type?: unknown }).type || '')}</div>;
          }
        } catch {
          return <div key={key} className="message-content message-part-notice warning">{String(part.type)}</div>;
        }
      })}
    </div>
  );
}

export function hasRenderableParts(parts: MessagePart[] | undefined): boolean {
  return Array.isArray(parts) && parts.some(isRenderableMessagePart);
}

function stablePartKey(part: MessagePart, index: number): string {
  return typeof part.id === 'string' && part.id ? part.id : `${part.type}:${index}`;
}

function isRenderableMessagePart(part: MessagePart): boolean {
  if (!part || typeof part !== 'object') return false;
  if (part.type === 'text') return typeof part.text === 'string' && part.text.length > 0;
  if (part.type === 'json') return part.data !== undefined;
  if (part.type === 'file') return part.mode === 'inline_text' ? typeof part.content === 'string' : Boolean(part.attachment_id || part.url || part.filename);
  if (part.type === 'image') return Boolean(part.url || part.attachment_id || part.alt);
  if (part.type === 'media_group') return Array.isArray(part.items) && part.items.length > 0;
  if (part.type === 'form') return Boolean(part.form_id && Array.isArray(part.fields) && part.submit);
  if (part.type === 'command_buttons') return Array.isArray(part.buttons) && part.buttons.some((button) => button.label.trim() && button.message.trim());
  if (part.type === 'notice') return Boolean(part.text);
  if (part.type === 'error') return Boolean(part.message);
  return true;
}
