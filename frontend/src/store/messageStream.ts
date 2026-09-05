import type { Message, RuntimeEvent } from '../types';

export function applyMessageEvent(messages: Message[], event: RuntimeEvent): Message[] {
  const payload = event.payload || {};
  const id = event.message_id;
  if (!id) return messages;
  const index = messages.findIndex((m) => m.message_id === id);
  if (event.type === 'message_started') {
    if (index !== -1 || !payload.message) return messages;
    return [...messages, { ...payload.message as Message, metadata: { streaming: true, stream_seq: 0 } }];
  }
  if (event.type === 'message_completed') {
    if (!payload.message) return messages;
    const message = payload.message as Message;
    if (message.message_id !== id || message.session_id !== event.session_id) return messages;
    return index === -1 ? [...messages, message] : messages.map((m) => m.message_id === id ? message : m);
  }
  if (event.type !== 'message_delta' || index === -1) return messages;
  const message = messages[index];
  const seq = payload.seq;
  if (!message.metadata?.streaming || typeof seq !== 'number' || seq !== Number(message.metadata.stream_seq || 0) + 1 || typeof payload.delta !== 'string') return messages;
  const text = message.parts.filter((p) => p.type === 'text').map((p) => p.text).join('') + payload.delta;
  return messages.map((m) => m.message_id === id ? { ...m,
    metadata: { ...m.metadata, stream_seq: seq },
    parts: [{ id: id + '-text', type: 'text', format: 'markdown', text }],
  } : m);
}
