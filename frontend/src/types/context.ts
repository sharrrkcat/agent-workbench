import type { Attachment } from './messages';
import type { ContextPolicy } from './chat';

export type ContextBudgetStats = {
  configured_window_tokens: number; window_tokens: number; input_budget_tokens: number;
  input_tokens: number; counting: 'native' | 'estimated'; output_tokens: number;
  margin_tokens: number; removed_turns: number;
};
export type ContextSummary = { available: true; message_count: number; tool_count: number; image_count: number;
  budget?: ContextBudgetStats | null };
export type ContextSourceKind = 'system' | 'agent_persona' | 'project_prompt' | 'cogita_persona' | 'knowledge' |
  'knowledge_snippet' | 'history' | 'current_input' | 'attachment' | 'tool_call' | 'tool_result' | 'tools' | 'qq_runtime';
export type ContextAttachment = Pick<Attachment, 'id' | 'name' | 'type' | 'mime_type' | 'size' | 'uri'>;
export type ContextSource = {
  id: string; kind: ContextSourceKind; parent_id?: string | null;
  message_index?: number | null; part_index?: number | null;
  field?: 'message' | 'content' | 'tools'; start?: number; end?: number | null;
  reference_id?: string | null; turn_id?: string | null; name?: string | null; citation?: string | null;
  knowledge_base_id?: string | null; source_id?: string | null; role?: string | null;
  attachment?: ContextAttachment | null; text: string; char_count: number;
};
export type ContextExclusion = {
  kind: ContextSourceKind;
  reason: 'ineligible_history' | 'message_limit' | 'character_limit' | 'token_limit' | 'empty' | 'attachments_disabled' |
    'images_unsupported' | 'qq_image_unavailable' | 'qq_history_image' | 'qq_system_face' | 'qq_image_limit' |
    'file_text_disabled' | 'file_text_limit' | 'no_bindings' | 'no_results' | 'retrieval_failed';
  reference_id?: string | null; name?: string | null; count?: number;
};
type FunctionCall = { id: string; type?: 'function'; function: { name: string; arguments: string } };
export type ContextRequest = {
  model: string; stream: boolean; n?: 1;
  messages: Array<{
    role: 'system' | 'developer' | 'user' | 'assistant' | 'tool';
    content?: string | Array<{ type: 'text'; text: string } |
      { type: 'image_url'; image_url: { url: string; detail?: 'auto' | 'low' | 'high' } }> | null;
    reasoning_content?: string | null; name?: string | null; tool_calls?: FunctionCall[] | null; tool_call_id?: string | null;
  }>;
  tools?: Array<{ type?: 'function'; function: { name: string; description?: string | null; parameters?: Record<string, unknown>; strict?: boolean | null } }> | null;
  tool_choice?: 'none' | 'auto' | 'required' | { type?: 'function'; function: { name: string } } | null;
  parallel_tool_calls?: boolean | null;
  temperature?: number | null; top_p?: number | null; max_tokens?: number | null;
  presence_penalty?: number | null; frequency_penalty?: number | null; seed?: number | null; stop?: string | string[] | null;
  response_format?: { type: 'text' | 'json_object' | 'json_schema'; json_schema?: { name: string; description?: string | null; schema: Record<string, unknown>; strict?: boolean | null } | null } | null;
  stream_options?: { include_usage?: boolean } | null;
  reasoning_effort?: 'medium' | 'none' | null; chat_template_kwargs?: { enable_thinking: boolean } | null;
  cogita_request_options?: { skip_tool_capability_check?: boolean; skip_vision_capability_check?: boolean;
    skip_instant_capability_check?: boolean; skip_reasoning_capability_check?: boolean } | null;
};
export type ContextDetail = {
  reference_numbers?: Record<string, number>;
  run_id: string; step_id: string; captured_at: string; model_profile_id: string; model_alias: string;
  source_type: 'local' | 'provider'; request: ContextRequest; policy: ContextPolicy;
  sources: ContextSource[]; exclusions: ContextExclusion[]; attachment_ids: string[];
  budget?: ContextBudgetStats | null;
};
