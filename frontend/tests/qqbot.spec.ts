import { readFileSync } from 'node:fs';
import { test, expect, type APIResponse } from '@playwright/test';
import { chooseOption, openSidebar } from './controls';

const words = (locale: string, namespace: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));
async function json(response: Promise<APIResponse>) { const value = await response; expect(value.ok(), await value.text()).toBe(true); return value.json(); }

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  test.describe(`QQBot ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
    test('creation, immutable binding, settings and read-only conversation controls', async ({ page, request }, info) => {
      const labels = words(locale, 'personas'), runs = words(locale, 'runs'), chat = words(locale, 'chat');
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const model = (await json(request.get('/api/models/profiles'))).find((p: { kind: string }) => p.kind === 'llm');
      const account = String(Date.now());
      let projectId = '';
      try {
        await page.goto('/');
        await openSidebar(page);
        await page.locator('.session-sidebar').getByRole('button', { name: labels.newQQBot, exact: true }).click();
        const dialog = page.getByRole('dialog', { name: labels.newQQBot, exact: true });
        await expect(dialog).toBeVisible();
        await expect(dialog.getByLabel(labels.projectPrompt, { exact: true })).toHaveValue(labels.qq.defaultPrompt);
        await dialog.getByLabel(labels.projectName, { exact: true }).fill('QQ browser');
        await dialog.getByLabel(labels.qq.account, { exact: true }).fill(account);
        await dialog.getByLabel(labels.qq.token, { exact: true }).fill('fixture-secret');
        await chooseOption(dialog.getByLabel(labels.model, { exact: true }), model.name);
        await expect(dialog.getByLabel(labels.model, { exact: true })).toContainText(model.name);
        await expect(dialog.getByLabel(labels.defaultAgentPersona, { exact: true })).toContainText(labels.qq.noPersona);
        await expect(dialog.getByRole('switch', { name: labels.qq.enabled, exact: true })).not.toBeChecked();
        await dialog.getByLabel(labels.qq.keywords, { exact: true }).fill('BOT\nhello');
        await dialog.getByLabel(labels.qq.batchLimit, { exact: true }).fill('3');
        await expect(dialog.getByLabel(labels.qq.replyLimit, { exact: true })).toHaveValue('4');
        await dialog.getByLabel(labels.qq.replyLimit, { exact: true }).fill('3');
        await expect(dialog.getByRole('tab', { name: labels.knowledge, exact: true })).toHaveCount(0);
        const created = page.waitForResponse((r) => r.url().endsWith('/api/projects') && r.request().method() === 'POST');
        await dialog.getByRole('button', { name: labels.createProject, exact: true }).click();
        const project = await (await created).json();
        projectId = project.id;
        expect(project.kind).toBe('qqbot');
        expect(project.model_profile_id).toBe(model.id);
        expect(project.has_access_token).toBe(true);
        expect(project.access_token).toBeUndefined();
        expect(project.keywords).toEqual(['bot', 'hello']);
        expect(project.reply_message_limit).toBe(3);
        expect(project.system_prompt).toBe(labels.qq.defaultPrompt);
        await expect(dialog).toBeHidden();
        await expect(page).toHaveURL(new RegExp(`/projects/${projectId}$`));
        await expect(page.getByLabel(labels.qq.token, { exact: true })).toHaveValue('');
        await page.getByLabel(labels.projectPrompt, { exact: true }).fill('Project prompt');
        await page.getByLabel(labels.qq.replyLimit, { exact: true }).fill('2');
        await page.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(page.getByRole('button', { name: labels.save, exact: true })).toBeDisabled();
        expect((await json(request.get(`/api/projects/${projectId}`))).has_access_token).toBe(true);
        expect((await json(request.get(`/api/projects/${projectId}`))).reply_message_limit).toBe(2);
        expect((await json(request.get(`/api/projects/${projectId}`))).system_prompt).toBe('Project prompt');
        await page.getByLabel(labels.projectPrompt, { exact: true }).fill('');
        await page.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(page.getByRole('button', { name: labels.save, exact: true })).toBeDisabled();
        expect((await json(request.get(`/api/projects/${projectId}`))).system_prompt).toBe('');
        await page.getByRole('button', { name: labels.qq.clearToken, exact: true }).click();
        await page.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(page.getByRole('button', { name: labels.save, exact: true })).toBeDisabled();
        expect((await json(request.get(`/api/projects/${projectId}`))).has_access_token).toBe(false);
        await page.locator('.settings-scroll').evaluate((element) => { element.scrollTop = 0; });
        await page.screenshot({ path: info.outputPath('qq-settings.png') });
        await openSidebar(page);
        await page.locator(`[data-project-id="${projectId}"]`).getByRole('button', { name: labels.newProjectSession.replace('{{name}}', project.name), exact: true }).click();
        const bind = page.getByRole('dialog', { name: labels.qq.bindConversation, exact: true });
        await bind.getByLabel(labels.qq.sessionTitle, { exact: true }).fill('Bound QQ conversation');
        await chooseOption(bind.getByLabel(labels.qq.targetKind, { exact: true }), labels.qq.friend);
        await chooseOption(bind.getByLabel(labels.qq.targetKind, { exact: true }), labels.qq.group);
        await bind.getByLabel(labels.qq.targetId, { exact: true }).fill('7788');
        const bound = page.waitForResponse((r) => r.url().endsWith(`/api/projects/${projectId}/sessions`) && r.request().method() === 'POST');
        await bind.getByRole('button', { name: labels.qq.bindConversation, exact: true }).click();
        const session = await (await bound).json();
        await expect(bind).toBeHidden();
        await expect(page.getByRole('heading', { name: session.title, exact: true })).toBeVisible();
        await expect(page.getByRole('textbox', { name: labels.qq.readOnly })).toBeDisabled();
        await expect(page.getByRole('button', { name: labels.send, exact: true })).toBeDisabled();
        await expect(page.getByRole('button', { name: labels.model, exact: true })).toBeDisabled();
        if (width === 390) await expect(page.locator('.session-sidebar')).toBeHidden();
        await json(request.post(`/__test__/qq/${session.session_id}`));
        await expect(page.getByText('qq-fixture bot', { exact: false })).toBeVisible();
        await expect(page.locator('[data-qq-incoming]').last()).toContainText('@QQ bot@Mentioned member');
        await page.locator('[data-qq-incoming]').last().getByRole('button').click();
        await expect(page.locator('[data-slot="tooltip-content"]')).toContainText(`QQ: ${account}`);
        await expect(page.locator('[data-slot="tooltip-content"]')).toContainText(labels.qq.botSelf);
        await page.keyboard.press('Escape');
        await expect(page.locator('[data-qq-incoming]')).toHaveCount(50);
        await expect(page.locator('.message-row.user [data-slot="message-avatar"]')).toHaveCount(1);
        await expect(page.locator('.message-row.user [data-slot="avatar-fallback"]')).toHaveText('Q');
        await expect(page.getByRole('tab')).toHaveCount(0);
        await page.getByRole('button', { name: chat.loadEarlier, exact: true }).click();
        await expect(page.locator('[data-qq-incoming]')).toHaveCount(65);
        await expect(page.getByRole('button', { name: chat.loadEarlier, exact: true })).toHaveCount(0);
        await expect(page.getByText('Record 1[图片]', { exact: true })).toBeAttached();
        await expect(page.locator('.message-row.user [data-slot="message-avatar"]')).toHaveCount(1);
        await page.getByRole('button', { name: chat.scrollToEnd, exact: true }).click();
        await expect(page.locator('.message-row.user time')).toHaveCount(1);
        await expect(page.locator('[data-qq-continuation]')).toHaveCount(64);
        await expect(page.locator('[data-qq-continuation] .message-meta')).toHaveCount(0);
        await expect(page.locator('[data-qq-incoming] button')).toHaveCount(65);
        const continuationGap = await page.locator('[data-qq-continuation]').first().evaluate((element) =>
          element.getBoundingClientRect().top - element.previousElementSibling!.getBoundingClientRect().bottom);
        expect(continuationGap).toBeCloseTo(6, 1);
        await page.getByRole('button', { name: labels.qq.pause, exact: true }).click();
        await expect(page.getByRole('button', { name: labels.qq.resume, exact: true })).toBeVisible();
        await page.getByRole('button', { name: labels.qq.resume, exact: true }).click();
        await page.getByRole('button', { name: labels.qq.stop, exact: true }).click();
        await expect(page.getByRole('button', { name: labels.qq.resume, exact: true })).toBeVisible();
        const delivery = page.locator('[data-qq-delivery]').first();
        await expect(delivery.getByText('Confirmed QQ reply', { exact: true })).toBeVisible();
        await expect(delivery.locator('[data-slot="bubble"]')).toHaveAttribute('data-variant', 'secondary');
        await delivery.getByRole('button', { name: labels.qq.status.sent, exact: true }).click();
        await expect(page.locator('[data-slot="tooltip-content"]')).toContainText(labels.qq.externalId + ': 9001');
        await expect(page.getByText('Internal QQ prose', { exact: true })).toBeVisible();
        await expect(page.getByRole('button', { name: runs.retryReply, exact: true })).toHaveCount(0);
        await expect(page.getByRole('button', { name: runs.deleteReply, exact: true })).toHaveCount(0);
        await expect(page.getByRole('button', { name: labels.editMessage, exact: true })).toHaveCount(0);
        await page.getByRole('button', { name: runs.context.details, exact: true }).click();
        await expect(page.getByRole('dialog')).toBeVisible();
        await page.locator('[data-context-source="qq_runtime"]').click();
        await expect(page.locator('.context-source-detail')).toContainText('confirmed sends=1/2');
        await expect(page.locator('.context-source-detail')).toContainText(`your QQ account=${account}`);
        await page.keyboard.press('Escape');
        await expect(page.locator('[data-slot="dialog-content"]')).toHaveCount(0);
        await page.getByRole('button', { name: runs.metrics.details, exact: true }).click();
        await expect(page.getByRole('dialog')).toBeVisible();
        await page.keyboard.press('Escape');
        await expect(page.locator('[data-slot="dialog-content"]')).toHaveCount(0);
        await page.screenshot({ path: info.outputPath('qq-conversation.png') });
        // The browser fixtures below vary presentation states without changing the QQ service.
        await page.route(`**/api/qq/sessions/${session.session_id}/messages*`, async (route) => {
          const response = await route.fetch();
          const body = await response.json();
          for (const row of body.items) {
            if (row.external_id === '64') { row.sender_id = '8888'; row.sender_name = 'Second participant'; }
            if (row.external_id === '65') { row.disposition = 'pending'; row.text = 'QQ long message\n' + '长文本 / long text '.repeat(30); }
          }
          await route.fulfill({ response, json: body });
        });
        let echoed = false;
        await page.route(`**/api/qq/sessions/${session.session_id}/deliveries*`, async (route) => {
          const response = await route.fetch();
          const body = await response.json();
          const sent = body.items[0];
          if (sent) body.items = [
            { ...sent, echoed },
            ...['pending', 'sending', 'failed', 'unknown'].map((status, index) => ({
              ...sent, id: sent.id + index + 1, status, external_id: null, text: `Delivery ${status}`, error_code: status === 'failed' ? 'QQ_ACTION_FAILED' : null,
            })),
          ];
          await route.fulfill({ response, json: body });
        });
        await expect(page.locator('[data-qq-delivery]')).toHaveCount(5);
        await expect(page.locator('.message-row.user [data-slot="message-avatar"]')).toHaveCount(3);
        await expect(page.locator('[data-qq-delivery] .message-meta')).toHaveCount(0);
        await expect(page.locator('[data-qq-delivery] time')).toHaveCount(0);
        await expect(page.locator('.message-row.assistant time')).toHaveCount(1);
        const deliveryGaps = await page.locator('[data-qq-deliveries]').evaluate((element) => {
          const rows = Array.from(element.children);
          return {
            first: element.getBoundingClientRect().top - element.previousElementSibling!.getBoundingClientRect().bottom,
            between: rows.slice(1).map((row, index) => row.getBoundingClientRect().top - rows[index].getBoundingClientRect().bottom),
          };
        });
        expect(deliveryGaps.first).toBeCloseTo(8, 1);
        for (const gap of deliveryGaps.between) expect(gap).toBeCloseTo(6, 1);
        for (const status of ['pending', 'sending', 'sent', 'failed', 'unknown']) {
          await expect(page.locator('[data-qq-delivery]').getByRole('button', { name: labels.qq.status[status], exact: true })).toHaveCount(1);
        }
        echoed = true;
        await page.waitForResponse((response) => response.url().endsWith(`/qq/sessions/${session.session_id}/deliveries`));
        await expect(page.locator('[data-qq-delivery]')).toHaveCount(5);
        const incoming = page.locator('[data-qq-incoming]').last();
        const incomingBubble = incoming.locator('[data-slot="bubble"]');
        const statusIcon = incoming.getByRole('button');
        await expect(incomingBubble).toHaveAttribute('data-align', 'end');
        const bubbleBox = await incomingBubble.boundingBox(), iconBox = await statusIcon.boundingBox();
        expect(iconBox!.x + iconBox!.width).toBeLessThanOrEqual(bubbleBox!.x);
        const last = page.locator('[data-qq-delivery]').last();
        await last.scrollIntoViewIfNeeded();
        await page.screenshot({ path: info.outputPath('qq-delivery-states.png') });
        await incoming.scrollIntoViewIfNeeded();
        await page.screenshot({ path: info.outputPath('qq-participants.png') });
        const dimensions = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight,
          viewportWidth: innerWidth, viewportHeight: innerHeight,
          overflow: Array.from(document.querySelectorAll('body > *')).map((node) => ({
            tag: node.tagName, slot: node.getAttribute('data-slot'), rect: node.getBoundingClientRect().toJSON(),
          })),
        }));
        expect(dimensions.width, JSON.stringify(dimensions)).toBeLessThanOrEqual(dimensions.viewportWidth);
        expect(dimensions.height, JSON.stringify(dimensions)).toBeLessThanOrEqual(dimensions.viewportHeight);
        expect(errors).toEqual([]);
      } finally {
        if (projectId) await json(request.delete(`/api/projects/${projectId}`));
      }
    });

    test('reply limit completes normally and missing reply pauses with a clear error', async ({ page, request }, info) => {
      const labels = words(locale, 'personas');
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const model = (await json(request.get('/api/models/profiles'))).find((p: { kind: string }) => p.kind === 'llm');
      const project = await json(request.post('/api/projects', { data: {
        kind: 'qqbot', name: 'QQ reply policy', context_policy: {}, bot_account: String(Date.now()),
        websocket_url: 'ws://127.0.0.1:3001', model_profile_id: model.id, keywords: ['bot'], reply_message_limit: 2,
      } }));
      try {
        const session = await json(request.post(`/api/projects/${project.id}/sessions`, { data: { title: 'QQ reply policy', target_kind: 'group', target_id: '7788' } }));
        await page.goto(`/projects/${project.id}?session=${session.session_id}`);
        await expect(page.getByRole('heading', { name: session.title, exact: true })).toBeVisible();
        const limited = await json(request.post(`/__test__/qq/${session.session_id}/reply/limit`));
        await expect(page.locator('[data-qq-delivery]')).toHaveCount(2);
        await expect(page.locator('[data-qq-reply-limit]')).toHaveText(labels.qq.replyLimitReached.replace('{{sent}}', '2').replace('{{limit}}', '2'));
        await expect(page.getByRole('button', { name: labels.qq.pause, exact: true })).toBeVisible();
        const limitedRun = await json(request.get(`/api/runs/${limited.run_id}`));
        expect(limitedRun.status).toBe('DONE');
        expect(limitedRun.metadata.qq_reply).toEqual({ sent_count: 2, message_limit: 2, limit_reached: true });
        await page.screenshot({ path: info.outputPath('qq-reply-limit.png') });

        const missing = await json(request.post(`/__test__/qq/${session.session_id}/reply/missing`));
        await expect(page.getByRole('button', { name: labels.qq.resume, exact: true })).toBeVisible();
        await expect(page.getByRole('status').filter({ hasText: labels.qq.status.QQ_REPLY_REQUIRED })).toBeVisible();
        await expect(page.locator('.reply-error')).toContainText(labels.qq.status.QQ_REPLY_REQUIRED);
        await expect(page.locator('[data-qq-delivery]')).toHaveCount(2);
        const missingRun = await json(request.get(`/api/runs/${missing.run_id}`));
        expect(missingRun.status).toBe('FAILED');
        expect(missingRun.error_code).toBe('QQ_REPLY_REQUIRED');
        expect(missingRun.metadata.qq_reply.sent_count).toBe(0);
        await page.screenshot({ path: info.outputPath('qq-missing-reply.png') });
        expect(errors).toEqual([]);
      } finally {
        await json(request.delete(`/api/projects/${project.id}`));
      }
    });
  });
}
