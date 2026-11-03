import type { QQDelivery, QQHistoryItem, QQHistoryPage, QQMessage, QQHistoryPruned } from '../../api/qq';
import type { ToolRunResponse } from '../../types/tools';
import { buildReply, type Reply } from '../messages/turns';

export const QQ_WINDOW_LIMIT = 200;
export type QQHistoryDirection = 'before' | 'after' | 'around' | 'latest';
export class QQHistoryChanged extends Error {}

export function mergeQQHistory(current: QQHistoryPage | null, page: QQHistoryPage, direction: QQHistoryDirection): QQHistoryPage {
  if (!current || direction === 'around' || direction === 'latest') return page;
  if (current.history_version !== page.history_version) throw new QQHistoryChanged();
  // Adjacent pages already carry the authoritative order, including sub-microsecond delivery times.
  const adjacent = direction === 'before' ? [...page.items, ...current.items] : [...current.items, ...page.items];
  const rows = new Map(adjacent.map((item) => [item.id, item]));
  for (const item of page.items) rows.set(item.id, item);
  const ordered = [...rows.values()];
  const items = direction === 'before' ? ordered.slice(0, QQ_WINDOW_LIMIT) : ordered.slice(-QQ_WINDOW_LIMIT);
  return { ...page, items, before_cursor: items[0]?.cursor ?? null, after_cursor: items[items.length - 1]?.cursor ?? null,
    has_before: direction === 'before' ? page.has_before : current.has_before || ordered.length > items.length,
    has_after: direction === 'after' ? page.has_after : current.has_after || ordered.length > items.length };
}

export function pruneQQHistory(page: QQHistoryPage, change: QQHistoryPruned): QQHistoryPage {
  const runs = new Set(change.deleted_run_ids);
  return { ...page, items: page.items.flatMap((item): QQHistoryItem[] => {
    if (item.kind === 'incoming') return change.deleted_qq_message_ids.includes(item.message.id) ? [] : [item];
    if (item.kind === 'program') return change.deleted_qq_delivery_ids.includes(item.delivery.id) ? [] : [item];
    return runs.has(item.run.run_id) ? [] : [{ ...item,
      deliveries: item.deliveries.filter((row) => !change.deleted_qq_delivery_ids.includes(row.id)) }];
  }) };
}

export type QQConversationItem =
  | { kind: 'incoming'; id: string; message: QQMessage; showIdentity: boolean }
  | { kind: 'program'; id: string; delivery: QQDelivery }
  | { kind: 'reply'; id: string; reply: Reply; deliveries: QQDelivery[] };

export function buildQQConversation(items: QQHistoryItem[], details: Record<string, ToolRunResponse>): QQConversationItem[] {
  let groupStartedAt = 0;
  return items.map((item, index) => {
    if (item.kind === 'reply') {
      const detail = details[item.run.run_id];
      return { kind: 'reply', id: item.id, deliveries: item.deliveries,
        reply: buildReply(item.run, detail?.messages.filter((message) => message.metadata?.qq_delivery_id == null) ?? [],
          detail?.run.steps ?? item.run.steps ?? [], true) };
    }
    if (item.kind === 'program') return item;
    const previous = items[index - 1];
    const time = Date.parse(item.created_at);
    const showIdentity = previous?.kind !== 'incoming' || previous.message.sender_id !== item.message.sender_id
      || time - groupStartedAt > 120_000;
    if (showIdentity) groupStartedAt = time;
    return { ...item, showIdentity };
  });
}
