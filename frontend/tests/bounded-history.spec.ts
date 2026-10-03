import { expect, test } from '@playwright/test';
import { mockHistory } from './history';

for (const locale of ['en', 'zh-CN']) {
  for (const width of [1366, 390]) {
    test(`bounded history scroll and global numbering ${locale} ${width}`, async ({ page, request }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const session = await (await request.post('/__test__/session', { data: {} })).json();
      const messages = Array.from({ length: 650 }, (_, i) => ({ message_id: `history-${String(i).padStart(4, '0')}`,
        session_id: session.session_id, role: 'user', speaker_type: 'user', content_version: 2, run_id: null,
        created_at: new Date(Date.UTC(2026, 0, 1, 0, 0, i)).toISOString(), metadata: {},
        parts: [{ id: 't', type: 'text', format: 'plain', text: `Question ${i + 1}: bounded history.` }] }));
      await mockHistory(page, request, session.session_id, messages, []);
      await page.goto('/');
      const rows = page.locator('.message-row.user');
      const viewport = page.locator('.chat-scroll-container [data-slot="message-scroller-viewport"]');
      await expect(rows).toHaveCount(50);
      await expect(page.locator('.message-number').last()).toHaveText('#650');
      for (let i = 0; i < 5; i++) {
        const first = await rows.first().getAttribute('data-message-id');
        await viewport.dispatchEvent('wheel', { deltaY: -10000 });
        await viewport.evaluate((node) => { node.scrollTop = 0; node.dispatchEvent(new Event('scroll')); });
        await expect(page.locator('.message-number').first()).toHaveText(`#${551 - i * 50}`);
        await expect.poll(() => rows.count()).toBe(Math.min(100 + i * 50, 200));
        expect(await rows.count()).toBeLessThanOrEqual(200);
        if (first) await expect(page.locator(`[data-message-id="${first}"]`).first()).toBeAttached();
      }
      const latest = page.getByRole('button', { name: locale === 'en' ? 'Latest messages' : '最新消息', exact: true });
      await latest.click();
      await expect(rows).toHaveCount(50);
      await expect(page.locator('.message-number').last()).toHaveText('#650');
      if (width > 500) {
        const rail = page.locator('.user-message-navigation');
        await rail.getByRole('button', { name: locale === 'en' ? 'Load earlier messages' : '加载更早的消息', exact: true }).click();
        await expect(rail.locator('.user-message-tick')).toHaveCount(50);
        await rail.locator('.user-message-tick').first().click();
        await expect(rows.filter({ hasText: 'Question 551:' })).toBeInViewport();
        expect(await rows.count()).toBeLessThanOrEqual(200);
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
  }
}
