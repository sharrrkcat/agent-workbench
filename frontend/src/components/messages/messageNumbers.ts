import type { ConversationItem } from './turns';

export function messageNumbers(items: ConversationItem[]): ReadonlyMap<string, number> {
  const numbers = new Map<string, number>();
  let number = 0;
  items.forEach((item) => {
    if (item.kind === 'compaction') return;
    number++;
    numbers.set(item.id, number);
    if (item.kind === 'reply') {
      for (const message of item.reply.messages) numbers.set(message.message_id, number);
    }
  });
  return numbers;
}
