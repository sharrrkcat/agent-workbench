import type { CogitaState } from './state';
import type { HistoryMarker, HistoryPage, HistoryWindow } from '../../types/history';
import { compareTime, mergeMessages, mergeRuns, mergeSteps, retainedMessages, terminal } from './mergeState';

export const HISTORY_WINDOW_LIMIT = 200;
export type HistoryLoad = 'before' | 'after' | 'around' | 'latest';
const marker = ({ id, kind, number, cursor, created_at }: HistoryMarker): HistoryMarker => ({ id, kind, number, cursor, created_at });
const compare = (a: HistoryMarker, b: HistoryMarker) => compareTime(a.created_at, b.created_at)
  || (a.kind === b.kind ? a.id.localeCompare(b.id) : a.kind === 'message' ? -1 : 1);

function windowInfo(history: HistoryWindow, items: HistoryMarker[]): HistoryWindow {
  return { ...history, items, before_cursor: items[0]?.cursor ?? null, after_cursor: items[items.length - 1]?.cursor ?? null };
}

export function historyPageState(state: CogitaState, page: HistoryPage, mode: HistoryLoad,
  versions = { messages: state.messageVersion, runs: state.runVersion }): Partial<CogitaState> {
  const extending = mode === 'before' || mode === 'after';
  const previous = state.historyWindow;
  const markers = new Map((extending ? previous?.items ?? [] : []).map((item) => [item.id, item]));
  for (const item of page.items) markers.set(item.id, marker(item));
  const items = [...markers.values()].filter((i) => !state.deletedMessageIds.includes(i.id) && !state.deletedRunIds.includes(i.id)).sort(compare);
  const messages = retainedMessages(state, page.items.flatMap((item) => item.kind === 'message' ? [item.message] : item.messages));
  const runs = page.items.flatMap((item) => item.kind === 'reply' ? [item.run] : []);
  if (page.active_run && !state.deletedRunIds.includes(page.active_run.run_id)) runs.push(page.active_run);
  const liveMessages = state.messages.filter((m) => m.metadata?.streaming &&
    (runs.some((r) => r.run_id === m.run_id && !terminal(r.status))));
  const historyWindow = windowInfo({ history_version: page.history_version, before_cursor: page.before_cursor, after_cursor: page.after_cursor, items: [],
    has_before: mode === 'after' ? previous?.has_before ?? page.has_before : page.has_before,
    has_after: mode === 'before' ? previous?.has_after ?? page.has_after : page.has_after }, items);
  const combined = { ...state, historyWindow,
    messages: extending ? mergeMessages(state.messages, messages)
      : state.messageVersion !== versions.messages ? mergeMessages(messages, state.messages) : mergeMessages(liveMessages, messages),
    runs: mergeRuns(extending || state.runVersion !== versions.runs ? state.runs : [], runs),
    stepsByRunId: mergeSteps(extending || state.runVersion !== versions.runs ? state.stepsByRunId : {}, runs.flatMap((r) => r.steps || [])),
    historyFollowing: mode === 'latest' ? true : mode === 'around' || mode === 'before' ? false : state.historyFollowing,
  };
  // Event versions protect newer streaming data, but only identities in this window are retained.
  return { ...trimHistory(combined, mode === 'before'),
    historyFollowing: combined.historyFollowing, messageVersion: state.messageVersion + 1, runVersion: state.runVersion + 1 };
}

export function trimHistory(state: CogitaState, trimEnd = !state.historyFollowing): Partial<CogitaState> {
  const history = state.historyWindow;
  if (!history || !state.currentSession) return {};
  const markers = new Map(history.items.filter((i) => !state.deletedMessageIds.includes(i.id) && !state.deletedRunIds.includes(i.id))
    .map((item) => [item.id, item]));
  let next = Math.max(0, ...history.items.map((i) => i.number)) + 1;
  if (state.historyFollowing && !history.has_after) {
    const identities = [
      ...state.messages.filter((m) => m.role === 'user' || !m.run_id).map((m) => ({ id: m.message_id, kind: 'message' as const, created_at: m.created_at })),
      ...state.runs.map((r) => ({ id: r.run_id, kind: 'reply' as const, created_at: r.created_at })),
    ].sort((a, b) => compare(a as HistoryMarker, b as HistoryMarker));
    for (const item of identities) if (!markers.has(item.id) &&
      (!history.items.length || compare(item as HistoryMarker, history.items[history.items.length - 1]) > 0)) {
      const json = JSON.stringify({ session_id: state.currentSession.session_id, created_at: item.created_at,
        kind: item.kind === 'message' ? 0 : 1, id: item.id });
      const cursor = btoa(String.fromCharCode(...new TextEncoder().encode(json)));
      markers.set(item.id, { ...item, cursor, number: next++ });
    }
  }
  const ordered = [...markers.values()].sort(compare);
  const items = trimEnd ? ordered.slice(0, HISTORY_WINDOW_LIMIT) : ordered.slice(-HISTORY_WINDOW_LIMIT);
  const messageIds = new Set(items.filter((i) => i.kind === 'message').map((i) => i.id));
  const runIds = new Set(items.filter((i) => i.kind === 'reply').map((i) => i.id));
  const active = [...state.runs].reverse().find((r) => !terminal(r.status));
  return {
    historyWindow: windowInfo({ ...history,
      has_before: history.has_before || !trimEnd && ordered.length > HISTORY_WINDOW_LIMIT,
      has_after: history.has_after || trimEnd && ordered.length > HISTORY_WINDOW_LIMIT }, items),
    messages: state.messages.filter((m) => messageIds.has(m.message_id) || !!m.run_id && runIds.has(m.run_id)),
    runs: state.runs.filter((r) => runIds.has(r.run_id) || r.run_id === active?.run_id).map((r) => runIds.has(r.run_id) ? r : { ...r, steps: [] }),
    stepsByRunId: Object.fromEntries(Object.entries(state.stepsByRunId).filter(([id]) => runIds.has(id))),
  };
}
