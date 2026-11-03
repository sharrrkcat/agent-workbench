import { test, expect, type APIRequestContext } from '@playwright/test';

async function setup(request: APIRequestContext) {
  await request.post('/__test__/session');
  const profiles = await (await request.get('/api/models/profiles')).json();
  const model = profiles.find((item: { kind: string }) => item.kind === 'llm');
  const project = await (await request.post('/api/projects', { data: { kind: 'qqbot', name: 'QQ loading',
    model_profile_id: model.id, bot_account: String(Date.now()), websocket_url: 'ws://127.0.0.1:3001',
    keywords: ['bot'], context_policy: {} } })).json();
  const session = await (await request.post(`/api/projects/${project.id}/sessions`, {
    data: { target_kind: 'group', target_id: '7788' } })).json();
  return { project, session };
}

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  test.describe(`QQ loading ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: 900 }, hasTouch: width === 390 });
    test('bounded automatic pages preserve anchors and lazy processing leaves bubbles usable', async ({ page, request }) => {
      const { project, session } = await setup(request);
      let releaseDetail = () => {};
      try {
        await page.clock.install();
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
        const fixture = await (await request.post(`/__test__/qq/${session.session_id}/reply/limit`)).json();
        const base = await (await request.get(`/api/qq/sessions/${session.session_id}/history`)).json();
        const reply = base.items.find((item: { kind: string }) => item.kind === 'reply');
        const source = base.items.find((item: { kind: string }) => item.kind === 'incoming').message;
        const items = Array.from({ length: 650 }, (_, i) => ({ kind: 'incoming', id: `qq-message-${i + 1}`, cursor: String(i),
          created_at: new Date(Date.UTC(2026, 0, 1, 0, 0, i)).toISOString(),
          message: { ...source, id: i + 1, text: `Input ${i + 1}`, segments: [{ type: 'text', text: `Input ${i + 1}` }] } }));
        const timeline = [...items, { ...reply, cursor: '650', created_at: new Date(Date.UTC(2026, 0, 1, 0, 0, 650)).toISOString() }];
        const requests: string[] = [];
        let olderReads = 0;
        let version = base.history_version, calibrations = 0;
        page.on('request', (req) => { if (req.url().includes('/api/')) requests.push(req.url()); });
        await page.route(`**/api/qq/sessions/${session.session_id}/history*`, async (route) => {
          const params = new URL(route.request().url()).searchParams;
          if (params.has('before')) olderReads++;
          const limit = Number(params.get('limit') || 50);
          if (params.has('around') && limit === 100) calibrations++;
          let start = timeline.length - limit;
          if (params.has('before')) start = Math.max(0, Number(params.get('before')) - limit);
          if (params.has('after')) start = Number(params.get('after')) + 1;
          if (params.has('around')) start = Math.max(0, Number(params.get('around')) - Math.floor(limit / 2));
          const selected = timeline.slice(start, start + limit);
          await route.fulfill({ json: { ...base, history_version: version, binding: { ...base.binding, history_version: version },
            items: selected, has_before: start > 0, has_after: start + limit < timeline.length,
            before_cursor: selected[0]?.cursor, after_cursor: selected.at(-1)?.cursor } });
        });
        const detailGate = new Promise<void>((resolve) => { releaseDetail = resolve; });
        let detailReads = 0;
        await page.route(`**/api/tools/runs/${fixture.run_id}`, async (route) => {
          detailReads++; await detailGate; await route.continue();
        });
        await page.goto(`/projects/${project.id}?session=${session.session_id}`);
        const rows = page.locator('[data-qq-item]');
        const viewport = page.locator('[data-slot="message-scroller-viewport"]');
        await expect(rows).toHaveCount(50);
        await expect(page.locator('[data-qq-delivery]').first()).toBeVisible();
        expect(detailReads).toBe(0);
        expect(requests.filter((url) => url.includes(`/api/sessions/${session.session_id}/history`))).toEqual([]);
        await page.locator('.processing-toggle').click();
        await expect.poll(() => detailReads).toBe(1);
        await expect(page.locator('[data-qq-delivery]').first()).toBeVisible();
        const detailResponse = page.waitForResponse((response) => response.url().endsWith(`/api/tools/runs/${fixture.run_id}`));
        releaseDetail();
        await detailResponse;
        await page.locator('.processing-toggle').click();
        // Freeze polling time; explicit user scroll is the only cause of the following page reads.
        await page.clock.pauseAt(new Date(await page.evaluate(() => Date.now() + 1000)));
        for (let i = 0; i < 5; i++) {
          const before = await rows.first().getAttribute('data-message-id');
          await viewport.evaluate((node, touch) => {
            node.dispatchEvent(new Event(touch ? 'touchmove' : 'wheel', { bubbles: true }));
            node.scrollTop = 0;
            node.dispatchEvent(new Event('scroll', { bubbles: true }));
          }, width === 390);
          await page.clock.runFor(100);
          await expect(rows.first()).not.toHaveAttribute('data-message-id', before!);
          await expect.poll(() => rows.count()).toBe(Math.min(100 + i * 50, 200));
          await page.clock.runFor(16);
          if (before) {
            const kept = page.locator(`[data-qq-item][data-message-id="${before}"]`);
            await expect(kept).toBeAttached();
            await expect(kept).toBeInViewport();
          }
        }
        const readCount = olderReads;
        await viewport.evaluate((node) => { node.scrollTop = 0; node.dispatchEvent(new Event('scroll')); });
        await page.clock.runFor(200);
        expect(olderReads).toBe(readCount);
        const anchor = await rows.first().getAttribute('data-message-id');
        version++;
        await page.clock.runFor(1600);
        await expect.poll(() => calibrations).toBeGreaterThan(0);
        await expect(rows).toHaveCount(100);
        await page.clock.runFor(32);
        await expect(page.locator(`[data-qq-item][data-message-id="${anchor}"]`)).toBeInViewport();
        await page.getByRole('button', { name: locale === 'en' ? 'Latest messages' : '最新消息', exact: true }).click();
        await page.clock.runFor(100);
        await expect(rows).toHaveCount(50);
        await expect(page.locator('[data-qq-delivery]').first()).toBeVisible();
        expect(detailReads).toBe(1);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      } finally { releaseDetail(); await request.delete(`/api/projects/${project.id}`); }
    });

    test('connection form loads while options are slow and saves existing references', async ({ page, request }) => {
      const { project } = await setup(request);
      let release = () => {};
      const gate = new Promise<void>((resolve) => { release = resolve; });
      const requests: string[] = [];
      try {
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
        page.on('request', (req) => { if (req.url().includes('/api/')) requests.push(req.url()); });
        await page.route('**/api/models/profiles', async (route) => { await gate; await route.continue(); });
        await page.route('**/api/personas', async (route) => { await gate; await route.continue(); });
        await page.goto(`/projects/${project.id}`);
        const name = page.getByLabel(locale === 'en' ? 'Project name' : '项目名称', { exact: true });
        await expect(name).toHaveValue(project.name);
        await name.fill('Changed while options pending');
        await page.getByRole('button', { name: locale === 'en' ? 'Save' : '保存', exact: true }).click();
        await expect.poll(async () => (await (await request.get(`/api/projects/${project.id}`)).json()).name).toBe('Changed while options pending');
        const saved = await (await request.get(`/api/projects/${project.id}`)).json();
        expect(saved.model_profile_id).toBe(project.model_profile_id);
        expect(requests.filter((url) => /\/api\/models\/.*\/status|\/api\/models\/local-runtime|\/api\/sessions\/[^/]+\/history/.test(url))).toEqual([]);
        release();
        await expect(name).toHaveValue('Changed while options pending');
        await page.goto('/settings');
        await expect(page.locator('.settings-scroll')).toBeVisible();
        expect(requests.filter((url) => /\/api\/sessions\/[^/]+\/history/.test(url))).toEqual([]);
      } finally { release(); await request.delete(`/api/projects/${project.id}`); }
    });
  });
}
