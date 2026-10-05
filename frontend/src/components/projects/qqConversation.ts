import type { QQBatch, QQDelivery, QQMessage, QQPage } from '../../api/qq';
import type { ToolRunResponse } from '../../types/tools';
import { buildReply, type Reply } from '../messages/turns';

export type QQRows<T> = QQPage<T> & { initialized: boolean };
export const emptyQQRows = <T>(): QQRows<T> => ({ items: [], next_cursor: null, initialized: false, history_version: 0 });
export class QQHistoryChanged extends Error {}

// Follow the newest edge until it overlaps our saved window, including bursts larger than one page.
export async function refreshQQRows<T extends { id: number }>(current: QQRows<T>,
  fetchPage: (before?: number) => Promise<QQPage<T>>, unsettled: (row: T) => boolean): Promise<QQRows<T>> {
  const known = new Set(current.items.map((row) => row.id));
  const newest: T[] = [];
  let page = await fetchPage();
  const version = page.history_version;
  const read = async (before: number) => {
    const value = await fetchPage(before);
    if (value.history_version !== version) throw new QQHistoryChanged();
    return value;
  };
  newest.push(...page.items);
  if (current.initialized && version !== current.history_version) {
    // Replace the loaded range after deletion, including settled records far from the newest page.
    const oldest = current.items[current.items.length - 1]?.id;
    while (oldest !== undefined && page.next_cursor !== null && page.items[page.items.length - 1].id > oldest) {
      page = await read(page.next_cursor);
      newest.push(...page.items);
    }
    return { initialized: true, items: newest, next_cursor: page.next_cursor, history_version: version };
  }
  while (current.items.length && page.next_cursor !== null && !page.items.some((row) => known.has(row.id))) {
    page = await read(page.next_cursor);
    newest.push(...page.items);
  }
  const merged = new Map(current.items.map((row) => [row.id, row]));
  for (const row of newest) merged.set(row.id, row);
  const refreshed = new Set(newest.map((row) => row.id));
  // Older pending records can change even while the reader is far from the live edge.
  for (const row of current.items) {
    if (!unsettled(row) || refreshed.has(row.id)) continue;
    const updates = await read(row.id + 1);
    for (const update of updates.items) if (known.has(update.id)) {
      merged.set(update.id, update); refreshed.add(update.id);
    }
  }
  return { initialized: true, items: [...merged.values()].sort((a, b) => b.id - a.id),
    next_cursor: current.initialized && current.items.length ? current.next_cursor : page.next_cursor, history_version: version };
}

export async function olderQQRows<T extends { id: number }>(current: QQRows<T>, fetchPage: (before?: number) => Promise<QQPage<T>>): Promise<QQRows<T>> {
  if (current.next_cursor === null) return current;
  const page = await fetchPage(current.next_cursor);
  if (page.history_version !== current.history_version) throw new QQHistoryChanged();
  const rows = new Map(current.items.map((row) => [row.id, row]));
  for (const row of page.items) rows.set(row.id, row);
  return { initialized: true, items: [...rows.values()].sort((a, b) => b.id - a.id), next_cursor: page.next_cursor,
    history_version: page.history_version };
}

export type QQConversationItem =
  | { kind: 'incoming'; id: string; message: QQMessage; showIdentity: boolean }
  | { kind: 'reply'; id: string; reply: Reply; deliveries: QQDelivery[] };

export function buildQQConversation(messages: QQMessage[], batches: QQBatch[], deliveries: QQDelivery[], runs: Record<string, ToolRunResponse>): QQConversationItem[] {
  const entries: { time: number; order: number; item: QQConversationItem }[] = messages.map((message) => ({
    time: Date.parse(message.timestamp), order: message.id,
    item: { kind: 'incoming', id: `qq-message-${message.id}`, message, showIdentity: true },
  }));
  const ids = new Set([...batches.flatMap((batch) => batch.run_id ? [batch.run_id] : []), ...deliveries.map((row) => row.run_id)]);
  for (const id of ids) {
    const data = runs[id];
    if (!data) continue;
    const batchIds = new Set(batches.filter((batch) => batch.run_id === id).map((batch) => batch.id));
    const inputTimes = messages.filter((row) => row.batch_id !== null && batchIds.has(row.batch_id)).map((row) => Date.parse(row.timestamp));
    entries.push({ time: Math.max(Date.parse(data.run.created_at), ...inputTimes), order: Number.MAX_SAFE_INTEGER,
      item: { kind: 'reply', id: `qq-run-${id}`, reply: buildReply(data.run,
        data.messages.filter((message) => message.metadata?.qq_delivery_id == null), data.run.steps ?? []),
        deliveries: deliveries.filter((row) => row.run_id === id).sort((a, b) => a.id - b.id) } });
  }
  entries.sort((a, b) => a.time - b.time || a.order - b.order || a.item.id.localeCompare(b.item.id));
  let groupStartedAt = 0;
  return entries.map(({ item, time }, index) => {
    const previous = entries[index - 1]?.item;
    if (item.kind !== 'incoming') return item;
    const showIdentity = previous?.kind !== 'incoming' || previous.message.sender_id !== item.message.sender_id
      || time - groupStartedAt > 120_000;
    if (showIdentity) groupStartedAt = time;
    return { ...item, showIdentity };
  });
}
