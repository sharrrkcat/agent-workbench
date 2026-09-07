import type { Message } from '../types/messages';
import type { RuntimeEvent } from '../types/runs';

export function applyMessageEvent(messages: Message[], event: RuntimeEvent): Message[] {
  const payload = event.payload || {};
  const id = event.message_id;
  if (!id) return messages;
  const index = messages.findIndex((m) => m.message_id === id);
  if (event.type === 'message_started') {
    if (index !== -1 || !payload.message) return messages;
    const message = payload.message as Message;
    if (message.message_id !== id || message.session_id !== event.session_id) return messages;
    return [...messages, { ...message, metadata: { ...message.metadata, streaming: true, stream_seq: 0 } }];
  }
  if (['message_updated', 'message_completed', 'tool_call_created', 'tool_result_created'].includes(event.type)) {
    if (!payload.message) return messages;
    const message = payload.message as Message;
    if (message.message_id !== id || message.session_id !== event.session_id) return messages;
    return index === -1 ? [...messages, message] : messages.map((m) => m.message_id === id ? message : m);
  }
  if (event.type !== 'message_delta' || index === -1) return messages;
  const message = messages[index];
  const seq = payload.seq;
  const partId = payload.part_id;
  const kind = payload.part_type;
  if (!message.metadata?.streaming || typeof seq !== 'number' || seq !== Number(message.metadata.stream_seq || 0) + 1 || typeof payload.delta !== 'string' || typeof partId !== 'string' || !partId || !['text', 'reasoning'].includes(String(kind))) return messages;
  const part = message.parts.find((item) => item.id === partId);
  if (part && part.type !== kind) return messages;
  const next = kind === 'reasoning'
    ? { id: partId, type: 'reasoning' as const, text: (part?.type === 'reasoning' ? part.text : '') + payload.delta }
    : { id: partId, type: 'text' as const, format: 'markdown' as const, text: (part?.type === 'text' ? part.text : '') + payload.delta };
  return messages.map((m) => m.message_id === id ? { ...m,
    metadata: { ...m.metadata, stream_seq: seq },
    parts: part ? m.parts.map((item) => item.id === partId ? next : item) : [...m.parts, next],
  } : m);
}
