import type { Run } from './runs';

export type MessageRole = 'user' | 'assistant' | 'system' | 'tool';

export type TextPart = { id: string; type: 'text'; format?: 'plain' | 'markdown'; text: string };
export type ReasoningPart = { id: string; type: 'reasoning'; text: string };

export type JsonPart = { id: string; type: 'json'; data: unknown };

export type FilePart = {
  id: string;
  type: 'file';
  mode?: 'inline_text' | 'attachment_ref';
  content?: string;
  attachment_id?: string;
  filename?: string;
  language?: string;
  mime_type?: string;
  size?: number;
  truncated?: boolean;
  path?: string;
};

export type ImagePart = {
  id: string;
  type: 'image';
  url?: string;
  attachment_id?: string;
  alt?: string;
  title?: string;
  caption?: string;
};

export type AudioPart = {
  id: string;
  type: 'audio';
  source?: 'attachment' | 'url';
  attachment_id?: string;
  url: string;
  mime_type: string;
  filename?: string;
  title?: string;
  duration_ms?: number;
};

export type VideoPart = {
  id: string;
  type: 'video';
  source?: 'attachment' | 'url';
  attachment_id?: string;
  url: string;
  mime_type: string;
  filename?: string;
  title?: string;
  poster_url?: string;
};

export type NoticePart = { id: string; type: 'notice'; level?: 'info' | 'warning' | 'success'; text: string };

export type ErrorPart = { id: string; type: 'error'; code?: string; message: string };

export type ToolCallPart = {
  id: string;
  type: 'tool_call';
  tool_call_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
};

export type ToolResultPart = {
  id: string;
  type: 'tool_result';
  tool_call_id: string;
  tool_name: string;
  status: 'success' | 'error' | 'rejected' | 'cancelled';
  data?: unknown;
  error_code?: string;
  error_message?: string;
  truncated?: boolean;
};

export type MediaGroupPart = {
  id: string;
  type: 'media_group';
  layout?: 'gallery';
  items: Array<Pick<ImagePart, 'type' | 'url' | 'attachment_id' | 'alt' | 'title' | 'caption'>>;
};

export type MessagePart =
  | TextPart
  | ReasoningPart
  | JsonPart
  | FilePart
  | ImagePart
  | AudioPart
  | VideoPart
  | NoticePart
  | ErrorPart
  | MediaGroupPart
  | ToolCallPart
  | ToolResultPart;

export type Message = {
  message_id: string;
  session_id: string;
  role: MessageRole;
  speaker_type?: string | null;
  speaker_id?: string | null;
  speaker_name?: string | null;
  origin?: string | null;
  content_version?: number;
  parts: MessagePart[];
  run_id?: string | null;
  parent_message_id?: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
  run?: Run;
};

export type Attachment = {
  id: string;
  name: string;
  filename?: string;
  mime_type?: string;
  size_bytes?: number;
  uri?: string;
  url?: string;
  context_text?: string;
  text?: string;
  type?: string;
  [key: string]: unknown;
};

export type SendMessageAttachment = Record<string, unknown>;
