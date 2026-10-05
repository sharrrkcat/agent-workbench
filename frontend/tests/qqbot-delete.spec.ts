import { readFileSync } from 'node:fs';
import { test, expect, type APIResponse } from '@playwright/test';

const words = (locale: string, namespace: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));
async function json(response: Promise<APIResponse>) { const value = await response; expect(value.ok(), await value.text()).toBe(true); return value.json(); }

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  test.describe(`QQ deletion ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
    test('bubble deletion, confirmation, unchanged statuses and reply cascade', async ({ page, request }, info) => {
      const labels = words(locale, 'personas'), runs = words(locale, 'runs'), common = words(locale, 'common'), chat = words(locale, 'chat');
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const model = (await json(request.get('/api/models/profiles'))).find((p: { kind: string }) => p.kind === 'llm');
      const project = await json(request.post('/api/projects', { data: { kind: 'qqbot', name: 'QQ deletion', context_policy: {},
        bot_account: String(Date.now()), websocket_url: 'ws://127.0.0.1:3001', model_profile_id: model.id,
        keywords: ['bot'], batch_message_limit: 3, reply_message_limit: 2 } }));
      try {
        const session = await json(request.post(`/api/projects/${project.id}/sessions`, { data: { title: 'Delete QQ messages', target_kind: 'group', target_id: '7788' } }));
        const sid = session.session_id, base = `/api/qq/sessions/${sid}`;
        const firstRun = await json(request.post(`/__test__/qq/${sid}`));
        const secondRun = await json(request.post(`/__test__/qq/${sid}/reply/limit`));
        await page.goto(`/projects/${project.id}?session=${sid}`);
        await expect(page.locator('[data-qq-incoming]')).toHaveCount(50);
        await page.getByRole('button', { name: chat.loadEarlier, exact: true }).click();
        await expect(page.locator('[data-qq-incoming]')).toHaveCount(66);
        const messages = (await json(request.get(base + '/messages?limit=100'))).items;
        const selected = messages[0], kept = messages[1];
        const incoming = page.locator(`[data-qq-incoming="${selected.id}"]`);
        const remove = incoming.getByRole('button', { name: labels.qq.deleteMessage, exact: true });
        await incoming.scrollIntoViewIfNeeded();
        await page.mouse.move(0, 0);
        const before = (await incoming.locator('[data-slot="bubble"]').boundingBox())!;
        if (width === 1366) {
          await expect(remove).toHaveCSS('opacity', '0');
          await incoming.hover();
          await expect(remove).toHaveCSS('opacity', '1');
          expect((await incoming.locator('[data-slot="bubble"]').boundingBox())!.x).toBeCloseTo(before.x, 1);
          await page.mouse.move(0, 0);
          await remove.focus();
          await expect(remove).toHaveCSS('opacity', '1');
        } else {
          await expect(remove).toHaveCSS('opacity', '1');
          const box = (await remove.boundingBox())!;
          expect(box.width).toBeGreaterThanOrEqual(44); expect(box.height).toBeGreaterThanOrEqual(44);
        }
        const buttonBox = (await remove.boundingBox())!;
        const statusBox = (await incoming.getByRole('button', { name: labels.qq.status.batched, exact: true }).boundingBox())!;
        expect(buttonBox.x + buttonBox.width).toBeLessThanOrEqual(statusBox.x);
        expect(statusBox.x + statusBox.width).toBeLessThanOrEqual(before.x);
        await page.screenshot({ path: info.outputPath('qq-delete-hover.png') });
        await remove.click();
        await expect(page.getByRole('alertdialog')).toContainText(labels.qq.deleteMessageConfirm);
        await page.getByRole('button', { name: common.cancel, exact: true }).click();
        await expect(incoming).toHaveCount(1);

        // Failed deletion must leave a durable error and the unchanged bubble.
        await page.route(`**${base}/messages/${selected.id}`, (route) => route.fulfill({ status: 409,
          contentType: 'application/json', body: JSON.stringify({ error: { code: 'SESSION_BUSY', message: 'Fixture busy' } }) }));
        await remove.click();
        await page.getByRole('button', { name: common.confirm, exact: true }).click();
        await expect(page.getByRole('alert').filter({ hasText: 'Fixture busy' })).toBeVisible();
        await expect(incoming).toHaveCount(1);
        await page.unroute(`**${base}/messages/${selected.id}`);
        await remove.click();
        await page.getByRole('button', { name: common.confirm, exact: true }).click();
        await expect(incoming).toHaveCount(0);
        await expect(page.locator('[data-qq-incoming]')).toHaveCount(65);
        await expect(page.locator(`[data-qq-incoming="${kept.id}"]`).getByRole('button', { name: labels.qq.status[kept.disposition], exact: true })).toBeAttached();
        await expect(page.locator(`[data-run-id="${secondRun.run_id}"]`)).toHaveCount(1);

        const deliveries = (await json(request.get(base + '/deliveries'))).items;
        const targets = deliveries.filter((row: { run_id: string }) => row.run_id === secondRun.run_id);
        const outgoing = page.locator(`[data-qq-delivery="${targets[0].id}"]`);
        await outgoing.scrollIntoViewIfNeeded();
        if (width === 1366) await outgoing.hover();
        const positions = await outgoing.locator('[data-qq-bubble-row]').evaluate((node) => Array.from(node.children).map((child) => child.getBoundingClientRect().x));
        expect(positions).toEqual([...positions].sort((a, b) => a - b));
        await outgoing.getByRole('button', { name: labels.qq.deleteMessage, exact: true }).click();
        await page.getByRole('button', { name: common.confirm, exact: true }).click();
        await expect(outgoing).toHaveCount(0);
        await expect(page.locator(`[data-qq-delivery="${targets[1].id}"]`).getByRole('button', { name: labels.qq.status.sent, exact: true })).toBeAttached();
        await expect(page.locator(`[data-run-id="${secondRun.run_id}"]`)).toHaveCount(1);

        // A busy response disables every delete entry without enabling regeneration.
        await page.route(`**${base}`, async (route) => { const response = await route.fetch(); await route.fulfill({ response, json: { ...await response.json(), busy: true } }); });
        const replyDelete = page.locator(`[data-run-id="${secondRun.run_id}"]`).getByRole('button', { name: runs.deleteReply, exact: true });
        await expect(replyDelete).toBeDisabled();
        await expect(page.locator('[data-qq-delete]:not(:disabled)')).toHaveCount(0);
        await page.unroute(`**${base}`);
        await expect(replyDelete).toBeEnabled();
        await expect(page.getByRole('button', { name: runs.retryReply, exact: true })).toHaveCount(0);
        await replyDelete.click();
        await expect(page.getByRole('alertdialog')).toContainText(labels.qq.deleteReplyConfirm);
        await page.getByRole('button', { name: common.confirm, exact: true }).click();
        await expect(page.locator(`[data-run-id="${secondRun.run_id}"]`)).toHaveCount(0);
        await expect(page.locator(`[data-qq-delivery="${targets[1].id}"]`)).toHaveCount(0);
        await expect(page.locator(`[data-run-id="${firstRun.run_id}"]`)).toHaveCount(1);
        await expect(page.locator('[data-qq-incoming]')).toHaveCount(65);

        // Another client deletes an old settled bubble outside the newest page.
        const oldest = messages[messages.length - 1];
        await json(request.delete(base + `/messages/${oldest.id}`));
        await expect(page.locator(`[data-qq-incoming="${oldest.id}"]`)).toHaveCount(0);
        await expect(page.locator('[data-qq-incoming]')).toHaveCount(64);
        await page.reload();
        await expect(page.locator('[data-qq-incoming]')).toHaveCount(50);
        await page.getByRole('button', { name: chat.loadEarlier, exact: true }).click();
        await expect(page.locator('[data-qq-incoming]')).toHaveCount(64);
        await expect(page.locator('[data-qq-delivery]')).toHaveCount(1);
        const remaining = (await json(request.get(base + '/messages?limit=100'))).items;
        for (const row of remaining) expect(row.disposition).toBe(messages.find((old: { id: number }) => old.id === row.id).disposition);
        await page.screenshot({ path: info.outputPath('qq-delete-result.png') });
        expect(errors).toEqual([]);
      } finally { await json(request.delete(`/api/projects/${project.id}`)); }
    });
  });
}
