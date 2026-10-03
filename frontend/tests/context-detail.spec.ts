import { readMessages, mockHistory } from './history';
import { expect, test } from '@playwright/test';

for (const locale of ['en', 'zh-CN']) {
  for (const width of [1366, 390]) {
    test.describe(`context ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
      const zh = locale === 'zh-CN';
      const title = zh ? '上下文详情' : 'Context detail';
      const callLabel = zh ? '模型调用' : 'Model call';
      const requestLabel = zh ? '请求数据' : 'Request data';
      const structureLabel = zh ? '输入结构' : 'Input structure';
      const callName = (number: number) => zh ? `第 ${number} 次调用` : `Call ${number}`;
      test.beforeEach(async ({ page, request }) => {
        await request.post('/__test__/session', { data: {} });
        await page.addInitScript((language) => localStorage.setItem('cogita.locale', language), locale);
        await page.goto('/');
      });

      test('captures calls lazily, keeps exact request data and restores focus', async ({ page, request }, info) => {
        const contextRequests: string[] = [];
        page.on('request', (req) => { if (/\/steps\/[^/]+\/context$/.test(req.url())) contextRequests.push(req.url()); });
        await page.locator('.composer textarea').fill('two-rounds');
        await page.locator('.composer textarea').press('Enter');
        const reply = page.locator('article[data-run-id]').last();
        await expect(reply.getByRole('button', { name: title, exact: true })).toHaveCount(0);
        await expect(reply.locator('.reply-answer')).toContainText('aGk= decodes to hi.', { timeout: 20000 });
        await expect(page.locator('.message-number')).toHaveText(['#1', '#2']);
        const trigger = reply.getByRole('button', { name: title, exact: true });
        await expect(trigger).toBeVisible();
        expect(contextRequests).toHaveLength(0);
        const runId = await reply.getAttribute('data-run-id');
        const run = await (await request.get(`/api/runs/${runId}`)).json();
        const calls = run.steps.filter((step: { kind: string }) => step.kind === 'model');
        await trigger.scrollIntoViewIfNeeded();
        const before = (await trigger.boundingBox())!;
        await trigger.focus();
        await page.keyboard.press('Enter');
        const dialog = page.getByRole('dialog', { name: title });
        await expect(dialog).toBeVisible();
        await expect(dialog.getByRole('combobox', { name: callLabel })).toContainText(callName(3));
        await expect(dialog.locator('.context-source-detail')).toBeVisible();
        expect(contextRequests).toHaveLength(1);
        await dialog.getByRole('tab', { name: requestLabel }).click();
        const finalSnapshot = await (await request.get(`/api/runs/${runId}/steps/${calls[2].step_id}/context`)).json();
        expect(JSON.parse(await dialog.locator('.context-request').innerText())).toEqual(finalSnapshot.request);
        await dialog.getByRole('combobox', { name: callLabel }).click();
        await page.getByRole('option', { name: callName(1), exact: true }).click();
        await expect(dialog.locator('.context-request')).toBeVisible();
        const firstSnapshot = await (await request.get(`/api/runs/${runId}/steps/${calls[0].step_id}/context`)).json();
        expect(JSON.parse(await dialog.locator('.context-request').innerText())).toEqual(firstSnapshot.request);
        expect(firstSnapshot.request.messages.some((message: { role: string }) => message.role === 'tool')).toBe(false);
        await dialog.getByRole('tab', { name: structureLabel }).click();
        await dialog.locator('[data-context-source=current_input]').click();
        await expect(dialog.locator('.context-source-detail .context-text')).toHaveText('two-rounds');
        await dialog.getByRole('combobox', { name: callLabel }).click();
        await page.getByRole('option', { name: new RegExp(`^${callName(3)}`) }).click();
        await expect(dialog.locator('[data-context-source=tool_result]')).toHaveCount(2);
        expect(contextRequests).toHaveLength(2);
        const delayedSnapshot = await (await request.get(`/api/runs/${runId}/steps/${calls[1].step_id}/context`)).json();
        let release!: () => void;
        let started!: () => void;
        let finished!: () => void;
        const gate = new Promise<void>((resolve) => { release = resolve; });
        const waiting = new Promise<void>((resolve) => { started = resolve; });
        const delivered = new Promise<void>((resolve) => { finished = resolve; });
        await page.route(`**/steps/${calls[1].step_id}/context`, async (route) => {
          started();
          await gate;
          await route.fulfill({ json: delayedSnapshot });
          finished();
        });
        await dialog.getByRole('combobox', { name: callLabel }).click();
        await page.getByRole('option', { name: callName(2), exact: true }).click();
        await waiting;
        await dialog.getByRole('combobox', { name: callLabel }).click();
        await page.getByRole('option', { name: callName(1), exact: true }).click();
        await expect(dialog.locator('[data-context-source=tool_result]')).toHaveCount(0);
        release();
        await delivered;
        await expect(dialog.getByRole('combobox', { name: callLabel })).toContainText(callName(1));
        await expect(dialog.locator('[data-context-source=tool_result]')).toHaveCount(0);
        await dialog.getByRole('combobox', { name: callLabel }).click();
        await page.getByRole('option', { name: new RegExp(`^${callName(3)}`) }).click();
        await expect(page.getByRole('option')).toHaveCount(0);
        const overflow = await dialog.evaluate((node) => node.scrollWidth > node.clientWidth + 1);
        expect(overflow).toBe(false);
        await page.screenshot({ path: info.outputPath('context-detail.png') });
        await page.keyboard.press('Escape');
        await expect(dialog).toHaveCount(0);
        await expect(trigger).toBeFocused();
        await expect.poll(async () => Math.abs((await trigger.boundingBox())!.y - before.y)).toBeLessThan(3);
        if (width === 390) expect((await trigger.boundingBox())!.height).toBeGreaterThanOrEqual(44);
        await page.reload();
        await page.getByRole('button', { name: title, exact: true }).click();
        await expect(page.getByRole('dialog', { name: title }).locator('.context-source-detail')).toBeVisible();
      });

      test('message numbers match filtered history and renumber after deletion', async ({ page, request }) => {
        const input = page.locator('.composer textarea');
        await input.fill('first context');
        await input.press('Enter');
        await expect(page.getByRole('button', { name: title, exact: true })).toBeVisible();
        const firstRunId = await page.locator('article[data-run-id]').first().getAttribute('data-run-id');
        const firstRun = await (await request.get(`/api/runs/${firstRunId}`)).json();
        expect((await request.patch(`/api/sessions/${firstRun.session_id}`, { data: { context_policy: {
          max_messages: 1, max_chars: null, include_attachments: 'explicit',
        } } })).ok()).toBe(true);
        await input.fill('second context');
        await input.press('Enter');
        const trigger = page.getByRole('button', { name: title, exact: true }).last();
        await expect(page.locator('.message-number')).toHaveText(['#1', '#2', '#3', '#4']);
        await expect(page.getByRole('button', { name: zh ? '跳转到第 3 条消息：second context' : 'Go to message 3: second context', exact: true, includeHidden: true })).toHaveCount(1);
        await expect(page.locator('article[data-run-id]').last().getByRole('button', { name: title, exact: true })).toBeVisible();
        await trigger.click();
        const dialog = page.getByRole('dialog', { name: title });
        const history = dialog.locator('[data-context-source=history]');
        await expect(history.locator('.context-message-label')).toHaveText(zh ? '消息 #2' : 'Message #2');
        await expect(dialog.locator('[data-context-source=current_input] .context-message-label')).toHaveText(zh ? '消息 #3' : 'Message #3');
        await history.click();
        await expect(dialog.locator('.context-source-heading')).toContainText(zh ? '消息 #2' : 'Message #2');
        await page.keyboard.press('Escape');
        expect((await request.delete(`/api/runs/${firstRunId}`)).ok()).toBe(true);
        await expect(page.locator('.message-number')).toHaveText(['#1', '#2', '#3']);
        await page.reload();
        await expect(page.locator('.message-number')).toHaveText(['#1', '#2', '#3']);
        await page.getByRole('button', { name: title, exact: true }).click();
        await expect(history.locator('.context-message-label')).toHaveText(zh ? '已删除消息' : 'Deleted message');
        await expect(dialog.locator('[data-context-source=current_input] .context-message-label')).toHaveText(zh ? '消息 #2' : 'Message #2');
      });

      test('retries failed reads and closes when history is removed', async ({ page, request }) => {
        await page.locator('.composer textarea').fill('context 中文😀');
        await page.locator('.composer textarea').press('Enter');
        const reply = page.locator('article[data-run-id]').last();
        const trigger = reply.getByRole('button', { name: title, exact: true });
        await expect(trigger).toBeVisible();
        let fail = true;
        await page.route('**/steps/*/context', (route) => fail ? route.fulfill({ status: 503,
          json: { error: { code: 'UNAVAILABLE', message: 'Unavailable' } } }) : route.continue());
        await trigger.click();
        const dialog = page.getByRole('dialog', { name: title });
        await expect(dialog.getByRole('alert')).toBeVisible();
        fail = false;
        await dialog.getByRole('button', { name: zh ? '重试' : 'Retry', exact: true }).click();
        await expect(dialog.locator('.context-source-detail')).toBeVisible();
        await expect(dialog.getByRole('combobox', { name: callLabel })).toHaveCount(0);
        await dialog.locator('[data-context-source=current_input]').click();
        await expect(dialog.locator('.context-source-detail .context-text')).toHaveText('context 中文😀');
        const runId = await reply.getAttribute('data-run-id');
        await request.delete(`/api/runs/${runId}`);
        await expect(dialog).toHaveCount(0);
        await expect(page.getByRole('button', { name: title, exact: true })).toHaveCount(0);
      });

      test('closes on approval resume and stays closed when the answer finishes', async ({ page, request }) => {
        await page.locator('.composer textarea').fill('approval');
        await page.locator('.composer textarea').press('Enter');
        const reply = page.locator('article[data-run-id]').last();
        const trigger = reply.getByRole('button', { name: title, exact: true });
        await trigger.click();
        const dialog = page.getByRole('dialog', { name: title });
        await expect(dialog.locator('.context-source-detail')).toBeVisible();
        const runId = await reply.getAttribute('data-run-id');
        expect((await request.post(`/api/tools/approvals/${runId}`, { data: { decision: 'approve' } })).ok()).toBe(true);
        await expect(reply.locator('.reply-answer')).toContainText('Browser final answer.');
        await expect(dialog).toHaveCount(0);
        await trigger.click();
        await expect(dialog.getByRole('combobox', { name: callLabel })).toContainText(callName(2));
        await expect(dialog.locator('[data-context-source=tool_result]')).toHaveCount(1);
      });

      test('previews the referenced image without counting its URL as text', async ({ page }, info) => {
        const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j1ioAAAAASUVORK5CYII=', 'base64');
        await expect(page.locator('.composer input[type=file]')).toBeEnabled();
        await page.locator('.composer input[type=file]').setInputFiles({ name: 'context.png', mimeType: 'image/png', buffer: png });
        await expect(page.locator('.upload-ready')).toHaveCount(1);
        await page.locator('.composer textarea').fill('image context');
        await page.locator('.composer textarea').press('Enter');
        await page.getByRole('button', { name: title, exact: true }).click();
        const dialog = page.getByRole('dialog', { name: title });
        await expect(dialog.locator('.context-source-detail')).toBeVisible();
        const expand = zh ? '展开或收起 消息 #1' : 'Expand or collapse Message #1';
        await dialog.getByRole('button', { name: expand, exact: true }).click();
        const attachment = dialog.locator('[data-context-source=attachment]');
        await expect(attachment.locator('.context-tokens')).toHaveText('— tokens');
        await attachment.click();
        const image = dialog.getByRole('img', { name: 'context.png', exact: true });
        await expect(image).toBeVisible();
        await expect(image).toHaveJSProperty('naturalWidth', 1);
        await expect(dialog.locator('.context-source-detail')).toContainText('image/png');
        await expect(dialog.locator('.context-source-detail .context-text')).toContainText('local://attachments/');
        await page.screenshot({ path: info.outputPath('context-image.png') });
        await dialog.getByRole('tab', { name: requestLabel }).click();
        await expect(dialog.locator('.context-request')).not.toContainText('data:image/');
      });

      test('empty sources, token hover, info cards and independent scrolling', async ({ page, request }, info) => {
        let workerLoads = 0;
        let releaseWorker!: () => void;
        const workerGate = new Promise<void>((resolve) => { releaseWorker = resolve; });
        await page.route('**/*contextTokens.worker*.js', async (route) => { await workerGate; await route.continue(); });
        page.on('request', (req) => { if (req.url().includes('contextTokens.worker')) workerLoads++; });
        await page.locator('.composer textarea').fill('Hello, world!');
        await page.locator('.composer textarea').press('Enter');
        const trigger = page.getByRole('button', { name: title, exact: true });
        await expect(trigger).toBeVisible();
        expect(workerLoads).toBe(0);
        const runId = await page.locator('article[data-run-id]').last().getAttribute('data-run-id');
        const run = await (await request.get(`/api/runs/${runId}`)).json();
        const call = run.steps.find((step: { kind: string }) => step.kind === 'model');
        const snapshot = await (await request.get(`/api/runs/${runId}/steps/${call.step_id}/context`)).json();
        const current = snapshot.sources.find((source: { kind: string }) => source.kind === 'current_input');
        const sessionMessages = await readMessages(request, run.session_id);
        const originalUser = sessionMessages.find((message: { message_id: string }) => message.message_id === current.reference_id);
        const numberedMessages = Array.from({ length: 105 }, (_, i) => ({ ...originalUser,
          message_id: `numbered-${i}`, created_at: new Date(Date.UTC(2020, 0, 1, 0, 0, i)).toISOString(),
          parts: [{ id: `text-${i}`, type: 'text', text: `Earlier message ${i + 1}` }], run: null, run_id: null }));
        await mockHistory(page, request, run.session_id, [...numberedMessages, ...sessionMessages]);
        await page.reload();
        await expect(page.locator('.message-number').last()).toHaveText('#107');
        const longText = 'scrollable content\n'.repeat(250);
        await page.route('**/steps/*/context', (route) => route.fulfill({ json: { ...snapshot,
          sources: [...snapshot.sources, ...Array.from({ length: 45 }, (_, i) => ({ id: `history-${i}`, kind: 'history',
            reference_id: `numbered-${i + 60}`, role: 'user', message_index: i + 2, text: longText, char_count: longText.length }))] } }));
        await trigger.click();
        const dialog = page.getByRole('dialog', { name: title });
        const backdrop = page.locator('[data-slot=dialog-overlay]');
        await expect(backdrop).toBeVisible();
        await expect(backdrop).not.toHaveCSS('backdrop-filter', 'none');
        const nav = dialog.locator('.context-sources');
        await expect(nav.locator('[data-context-source=system] > span').first()).toHaveText('System');
        await expect(dialog.locator('.context-source-heading > span').first()).toHaveText('System');
        await expect(nav.getByText(zh ? '实际发送顺序' : 'Actual send order', { exact: true })).toHaveCount(0);
        await expect(dialog.locator('.context-call-header [data-slot=badge]')).toHaveCount(4);
        const badges = dialog.locator('.context-call-header [data-slot=badge]');
        expect(await badges.first().evaluate((node) => getComputedStyle(node).backgroundColor))
          .not.toEqual(await badges.nth(1).evaluate((node) => getComputedStyle(node).backgroundColor));
        const empty = nav.locator('[data-context-source=cogita_persona]');
        await expect(empty).toHaveAttribute('data-empty', 'true');
        await expect(empty).toContainText(zh ? '空' : 'Empty');
        await expect(nav.locator('[data-context-source=knowledge]')).toHaveAttribute('data-empty', 'true');
        await expect(dialog.locator('.context-exclusions')).toHaveCount(0);
        await empty.click();
        await expect(dialog.locator('.context-source-detail [data-slot=empty]')).toContainText(zh ? '空' : 'Empty');
        const currentRow = nav.locator('[data-context-source=current_input]');
        await currentRow.click();
        const countBefore = await currentRow.locator('.context-count').boundingBox();
        const charsBefore = await currentRow.locator('.context-chars').boundingBox();
        releaseWorker();
        await expect(currentRow.locator('.context-tokens')).toHaveText('≈ 4 tokens');
        await expect(currentRow.locator('.context-message-label')).toHaveText(zh ? '消息 #106' : 'Message #106');
        expect(await currentRow.locator('.context-count').boundingBox()).toEqual(countBefore);
        expect(await currentRow.locator('.context-chars').boundingBox()).toEqual(charsBefore);
        expect(workerLoads).toBe(1);
        if (width === 1366) {
          await dialog.getByRole('tab', { name: structureLabel }).focus();
          await dialog.getByRole('heading', { name: title }).hover();
          await expect(currentRow.locator('.context-chars')).toHaveCSS('visibility', 'visible');
          await currentRow.hover();
          await expect(currentRow.locator('.context-tokens')).toHaveCSS('visibility', 'visible');
          await expect(currentRow.locator('.context-chars')).toHaveCSS('visibility', 'hidden');
        }
        const infoButton = dialog.getByRole('button', { name: zh ? '来源信息' : 'Source information' });
        if (width === 390) await infoButton.tap(); else await infoButton.focus();
        const card = page.locator('[data-slot=hover-card-content]');
        await expect(card).toContainText('≈ 4 tokens');
        await expect(card).toHaveCSS('opacity', '1');
        expect(await card.evaluate((node) => {
          const rect = node.getBoundingClientRect();
          return node.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2));
        })).toBe(true);
        await expect(card).not.toContainText(zh ? '统一参考分词估算' : 'Estimated with a shared reference tokenizer');
        await expect(card).toContainText(current.reference_id);
        await expect(dialog.locator('.context-source-detail')).not.toContainText(current.reference_id);
        await page.screenshot({ path: info.outputPath('context-info.png'), animations: 'disabled' });
        await nav.locator('[data-context-source=history]').first().click();
        await expect(card).toHaveCount(0);
        const numberedRow = nav.locator('[data-context-source=history]').last();
        await numberedRow.scrollIntoViewIfNeeded();
        await expect(numberedRow.locator('.context-message-label')).toHaveText(zh ? '消息 #105' : 'Message #105');
        await expect(numberedRow.locator('.context-tokens')).toContainText('≈');
        const rowBefore = await numberedRow.boundingBox();
        if (width === 1366) await numberedRow.hover(); else await numberedRow.tap();
        expect((await numberedRow.boundingBox())!.height).toBe(rowBefore!.height);
        expect(await numberedRow.locator('.context-message-label').evaluate((node) => {
          const range = document.createRange();
          range.selectNodeContents(node);
          return range.getClientRects().length;
        })).toBe(1);
        expect(await numberedRow.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
        const panel = dialog.locator('.context-source-detail');
        const tabsY = (await dialog.getByRole('tab', { name: structureLabel }).boundingBox())!.y;
        const navTop = await nav.evaluate((node) => node.scrollTop);
        await panel.evaluate((node) => { node.scrollTop = 300; });
        expect(await panel.evaluate((node) => node.scrollTop)).toBe(300);
        expect(await nav.evaluate((node) => node.scrollTop)).toBe(navTop);
        await nav.evaluate((node) => { node.scrollTop = 500; });
        expect(await panel.evaluate((node) => node.scrollTop)).toBe(300);
        expect((await dialog.getByRole('tab', { name: structureLabel }).boundingBox())!.y).toBe(tabsY);
        expect(await dialog.evaluate((node) => node.scrollWidth > node.clientWidth + 1)).toBe(false);
        await page.screenshot({ path: info.outputPath('context-scrolling.png') });
      });
    });
  }
}
