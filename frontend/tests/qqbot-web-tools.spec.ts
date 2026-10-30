import { readFileSync } from 'node:fs';
import { test, expect, type APIResponse } from '@playwright/test';

async function json(response: Promise<APIResponse>) { const value = await response; expect(value.ok(), await value.text()).toBe(true); return value.json(); }

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  test.describe(`QQ web tools ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: 900 }, hasTouch: width === 390 });
    for (const mode of ['web-research', 'web-failure']) {
      test(`${mode} reuses web settings and shows traces without citations`, async ({ page, request }, info) => {
        const runs = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/runs.json`, import.meta.url), 'utf8'));
        const errors: string[] = [];
        page.on('pageerror', (error) => errors.push(error.message));
        await json(request.post('/__test__/session', { data: { web_tools: true } }));
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
        const model = (await json(request.get('/api/models/profiles'))).find((p: { kind: string }) => p.kind === 'llm');
        const project = await json(request.post('/api/projects', { data: { kind: 'qqbot', name: 'QQ web research',
          model_profile_id: model.id, bot_account: String(Date.now()), websocket_url: 'ws://127.0.0.1:3001',
          keywords: ['bot'], reply_message_limit: 1, context_policy: {} } }));
        try {
          const session = await json(request.post(`/api/projects/${project.id}/sessions`, { data: { target_kind: 'group', target_id: '7788' } }));
          expect(session.effective.tools_allowed).toEqual(['qq_send_message', 'qq_skip_reply', 'web_fetch', 'web_search']);
          await page.goto(`/projects/${project.id}?session=${session.session_id}`);
          const fixture = await json(request.post(`/__test__/qq/${session.session_id}/reply/${mode}`));
          const reply = page.locator(`article[data-run-id="${fixture.run_id}"]`);
          const expected = mode === 'web-failure' ? 'Search unavailable; here is a reply.' : 'Here are the current facts from the web.';
          await expect(page.locator('[data-qq-delivery]')).toContainText(expected);
          await expect(reply.locator('.status-done')).toBeVisible();
          await reply.locator('.processing-toggle').click();
          const search = reply.locator('[data-web-tool=web_search]');
          await expect(search).toBeVisible();
          if (mode === 'web-failure') {
            await expect(search).toContainText(runs.web.errors.WEB_RATE_LIMITED);
          } else {
            await expect(search.locator('a')).toHaveCount(3);
            await expect(search.locator('a').first()).toHaveAttribute('href', /^https:\/\/example.com\/article\?query=/);
            await expect(search.locator('a').first()).toHaveAttribute('target', '_blank');
            const fetch = reply.locator('[data-web-tool=web_fetch]');
            await expect(fetch).toContainText('Extracted page content');
            await expect(fetch).not.toContainText('<script>');
            expect(await page.evaluate(() => (window as Window & { webPageExecuted?: boolean }).webPageExecuted)).toBeUndefined();
            await fetch.locator('[data-slot=trace-collapsible-trigger]').click();
            await expect(fetch.locator('[data-slot=trace-collapsible-trigger]')).toHaveAttribute('aria-expanded', 'false');
          }
          await expect(reply.locator('[data-web-citation], [data-web-sources], .approval-details')).toHaveCount(0);
          expect((await json(request.get(`/api/qq/sessions/${session.session_id}`))).paused).toBe(false);
          expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
          await page.screenshot({ path: info.outputPath('qq-web-trace.png'), fullPage: true });
          await page.reload();
          await expect(page.locator('[data-qq-delivery]')).toContainText(expected);
          await reply.locator('.processing-toggle').click();
          await expect(search).toBeVisible();
          await expect(reply.locator('[data-web-citation], [data-web-sources]')).toHaveCount(0);
          expect(errors).toEqual([]);
        } finally {
          await request.delete(`/api/projects/${project.id}`);
        }
      });
    }
  });
}
