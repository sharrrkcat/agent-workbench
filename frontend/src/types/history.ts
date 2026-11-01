import type { Message } from './messages';
import type { Run, RunEvent } from './runs';

export type HistoryMarker = {
  id: string; cursor: string; created_at: string;
} & ({ kind: 'message' | 'reply'; number: number } | { kind: 'compaction'; number: null });
export type HistoryItem = HistoryMarker & (
  { kind: 'message'; message: Message } | { kind: 'reply'; run: Run; messages: Message[] } | { kind: 'compaction'; run: Run }
);
export type HistoryWindow = {
  items: HistoryMarker[];
  before_cursor: string | null; after_cursor: string | null;
  has_before: boolean; has_after: boolean; history_version: number;
};
export type HistoryPage = Omit<HistoryWindow, 'items'> & { items: HistoryItem[]; active_run: Run | null };
export type HistoryUser = Omit<HistoryMarker, 'kind' | 'number'> & { kind: 'user'; number: number; summary: string };
export type HistoryUsersPage = Omit<HistoryWindow, 'items'> & { items: HistoryUser[] };
export type HistoryQuery = { before?: string; after?: string; around?: string; limit?: number };
export type RunEventsPage = { items: RunEvent[]; next_cursor: string | null; has_more: boolean };
