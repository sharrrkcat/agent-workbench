import type { Message } from './messages';
import type { Run, RunEvent } from './runs';

export type HistoryMarker = {
  id: string; kind: 'message' | 'reply'; number: number; cursor: string; created_at: string;
};
export type HistoryItem = HistoryMarker & (
  { kind: 'message'; message: Message } | { kind: 'reply'; run: Run; messages: Message[] }
);
export type HistoryWindow = {
  items: HistoryMarker[];
  before_cursor: string | null; after_cursor: string | null;
  has_before: boolean; has_after: boolean; history_version: number;
};
export type HistoryPage = Omit<HistoryWindow, 'items'> & { items: HistoryItem[]; active_run: Run | null };
export type HistoryUser = Omit<HistoryMarker, 'kind'> & { kind: 'user'; summary: string };
export type HistoryUsersPage = Omit<HistoryWindow, 'items'> & { items: HistoryUser[] };
export type HistoryQuery = { before?: string; after?: string; around?: string; limit?: number };
export type RunEventsPage = { items: RunEvent[]; next_cursor: string | null; has_more: boolean };
