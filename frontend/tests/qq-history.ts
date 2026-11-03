import { expect, type APIRequestContext } from '@playwright/test';
import type { QQHistoryPage } from '../src/api/qq';

export async function qqHistory(request: APIRequestContext, sessionId: string): Promise<QQHistoryPage> {
  const response = await request.get(`/api/qq/sessions/${sessionId}/history?limit=100`);
  expect(response.ok(), await response.text()).toBe(true);
  return response.json();
}

export async function qqDeliveries(request: APIRequestContext, sessionId: string) {
  const page = await qqHistory(request, sessionId);
  return page.items.flatMap((item) => item.kind === 'reply' ? item.deliveries : item.kind === 'program' ? [item.delivery] : [])
    .sort((a, b) => b.id - a.id);
}
