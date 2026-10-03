import type { APIRequestContext, Page } from '@playwright/test';
import { historyPage } from '../scripts/history-fixtures.mjs';

export async function readHistory(request: APIRequestContext, sessionId: string) {
  const items = [];
  let before: string | null = null;
  do {
    const response = await request.get(`/api/sessions/${sessionId}/history`, { params: { limit: 100, ...(before ? { before } : {}) } });
    if (!response.ok()) throw new Error(await response.text());
    const page = await response.json();
    items.unshift(...page.items);
    before = page.has_before ? page.before_cursor : null;
  } while (before);
  return items;
}

export async function readMessages(request: APIRequestContext, sessionId: string) {
  return (await readHistory(request, sessionId)).flatMap((item) => item.kind === 'message' ? [item.message] : item.messages);
}

export async function readRuns(request: APIRequestContext, sessionId: string) {
  return (await readHistory(request, sessionId)).flatMap((item) => item.kind === 'reply' ? [item.run] : []);
}

export async function mockHistory(page: Page, request: APIRequestContext, sessionId: string, messages: any[], suppliedRuns?: any[]) {
  const runs = suppliedRuns ?? await readRuns(request, sessionId);
  await page.route(`**/api/sessions/${sessionId}/history?*`, async (route) => {
    const params = Object.fromEntries(new URL(route.request().url()).searchParams);
    await route.fulfill({ json: historyPage(messages, runs, { ...params, ...(params.limit ? { limit: Number(params.limit) } : {}) }) });
  });
  await page.route(`**/api/sessions/${sessionId}/history/users?*`, async (route) => {
    const params = Object.fromEntries(new URL(route.request().url()).searchParams);
    const all = historyPage(messages, runs, { limit: messages.length + runs.length }).items;
    const users = all.filter((i: any) => i.kind === 'message' && i.message.role === 'user').map((i: any) => ({
      ...i, kind: 'user', summary: i.message.parts.find((p: any) => p.type === 'text')?.text?.slice(0, 160) || '', message: undefined }));
    const anchor = users.findIndex((i: any) => i.cursor === (params.before || params.after));
    const start = params.before ? Math.max(0, anchor - 50) : params.after ? anchor + 1 : Math.max(0, users.length - 50);
    const items = users.slice(start, params.before ? anchor : start + 50);
    await route.fulfill({ json: { items, before_cursor: items[0]?.cursor ?? null, after_cursor: items.at(-1)?.cursor ?? null,
      has_before: start > 0, has_after: start + items.length < users.length, history_version: 0, active_run: null } });
  });
}
