export function historyPage(messages = [], runs = [], query = {}) {
  const time = (value) => value || '2026-01-01T00:00:00.000000Z';
  const cursor = (item) => Buffer.from(JSON.stringify({ session_id: item.kind === 'message' ? item.message.session_id : item.run.session_id,
    created_at: item.created_at, kind: item.kind === 'message' ? 0 : 1, id: item.id })).toString('base64url');
  const items = [
    ...messages.filter((m) => m.role === 'user' || !m.run_id).map((message) => ({ kind: 'message', id: message.message_id, created_at: time(message.created_at), message })),
    ...runs.map((run) => ({ kind: 'reply', id: run.run_id, created_at: time(run.created_at), run,
      messages: messages.filter((m) => m.run_id === run.run_id) })),
  ].sort((a, b) => a.created_at.localeCompare(b.created_at) || (a.kind === b.kind ? a.id.localeCompare(b.id) : a.kind === 'message' ? -1 : 1))
    .map((item, index) => ({ ...item, number: index + 1, cursor: cursor(item) }));
  const limit = query.limit ?? 50;
  const anchor = items.findIndex((i) => i.cursor === (query.before || query.after || query.around));
  const start = query.before ? Math.max(0, anchor - limit) : query.after ? anchor + 1
    : query.around ? Math.max(0, anchor - Math.floor(limit / 2)) : Math.max(0, items.length - limit);
  const selected = items.slice(start, query.before ? anchor : start + limit);
  return { items: selected, before_cursor: selected[0]?.cursor ?? null, after_cursor: selected.at(-1)?.cursor ?? null,
    has_before: start > 0, has_after: start + selected.length < items.length, history_version: 0,
    active_run: runs.find((r) => ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(r.status)) ?? null };
}
