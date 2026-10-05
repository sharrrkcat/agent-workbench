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
        await expect(dialog.getByRole('switch', { name: labels.qq.imageInputEnabled, exact: true })).not.toBeChecked();
        await expect(dialog.getByRole('switch', { name: labels.qq.icebreakerEnabled, exact: true })).not.toBeChecked();
        await expect(dialog.getByLabel(labels.qq.icebreakerCold, { exact: true })).toHaveCount(0);
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
        expect(project.image_input_enabled).toBe(false);
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
        const hint = labels.qq.chattingIn.replace('{{targetId}}', session.target_id);
        await expect(page.getByRole('textbox', { name: hint, exact: true })).toBeDisabled();
        await expect(page.getByRole('textbox', { name: hint, exact: true })).toHaveAttribute('placeholder', hint);
        await expect(page.getByRole('button', { name: labels.send, exact: true })).toHaveCount(0);
        await expect(page.getByRole('button', { name: labels.attach, exact: true })).toHaveCount(0);
        await expect(page.getByRole('button', { name: labels.model, exact: true })).toBeEnabled();
        await expect(page.locator('.topbar').getByText(session.target_id, { exact: true })).toHaveCount(0);
        await expect(page.locator('.topbar').getByRole('button', { name: labels.qq.pause, exact: true })).toHaveCount(0);
        if (width === 390) await expect(page.locator('.session-sidebar')).toBeHidden();
        await json(request.post(`/__test__/qq/${session.session_id}`));
        await expect(page.getByText('qq-fixture bot', { exact: false })).toBeVisible();
        await expect(page.locator('[data-qq-incoming]').last()).toContainText('@QQ bot@Mentioned member');
        await page.locator('[data-qq-incoming]').last().getByRole('button', { name: labels.qq.status.batched, exact: true }).click();
        const incomingStatusTip = page.locator('[data-slot="tooltip-content"]').filter({ hasText: labels.qq.status.batched });
        await expect(incomingStatusTip).toContainText(`QQ: ${account}`);
        await expect(incomingStatusTip).toContainText(labels.qq.botSelf);
        await page.keyboard.press('Escape');
        await expect(page.locator('[data-qq-incoming]')).toHaveCount(50);
        await expect(page.locator('.message-row.user [data-slot="message-avatar"]')).toHaveCount(1);
        await expect(page.locator('.message-row.user [data-slot="avatar-fallback"]')).toHaveText('Q');
        await expect(page.getByRole('tab')).toHaveCount(0);
        await page.getByRole('button', { name: chat.loadEarlier, exact: true }).click();
        await expect(page.locator('[data-qq-incoming]')).toHaveCount(65);
        await expect(page.getByRole('button', { name: chat.loadEarlier, exact: true })).toHaveCount(0);
        await expect(page.getByText('Record 1', { exact: true })).toBeAttached();
        await expect(page.locator('[data-qq-media-state="pending"]')).toHaveCount(65);
        await expect(page.locator('.message-row.user [data-slot="message-avatar"]')).toHaveCount(1);
        await page.getByRole('button', { name: chat.scrollToEnd, exact: true }).click();
        await expect(page.locator('.message-row.user time')).toHaveCount(1);
        await expect(page.locator('[data-qq-continuation]')).toHaveCount(64);
        await expect(page.locator('[data-qq-continuation] .message-meta')).toHaveCount(0);
        await expect(page.locator('[data-qq-incoming] button')).toHaveCount(130);
        const continuationGap = await page.locator('[data-qq-continuation]').first().evaluate((element) =>
          element.getBoundingClientRect().top - element.previousElementSibling!.getBoundingClientRect().bottom);
        expect(continuationGap).toBeCloseTo(6, 1);
        await page.locator('.composer').getByRole('button', { name: labels.qq.pause, exact: true }).click();
        await expect(page.getByRole('button', { name: labels.qq.resume, exact: true })).toBeVisible();
        await page.getByRole('button', { name: labels.qq.resume, exact: true }).click();
        await page.getByRole('button', { name: labels.qq.stop, exact: true }).click();
        await expect(page.getByRole('button', { name: labels.qq.resume, exact: true })).toBeVisible();
        const delivery = page.locator('[data-qq-delivery]').first();
        await expect(delivery.getByText('Confirmed QQ reply', { exact: true })).toBeVisible();
        await expect(delivery.locator('[data-slot="bubble"]')).toHaveAttribute('data-variant', 'secondary');
        await delivery.getByRole('button', { name: labels.qq.status.sent, exact: true }).click();
        await expect(page.locator('[data-slot="tooltip-content"]').filter({ hasText: labels.qq.status.sent })).toContainText(labels.qq.externalId + ': 9001');
        await expect(page.getByText('Internal QQ prose', { exact: true })).toBeVisible();
        await expect(page.getByRole('button', { name: runs.retryReply, exact: true })).toHaveCount(0);
        await expect(page.getByRole('button', { name: runs.deleteReply, exact: true })).toHaveCount(1);
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
            if (row.external_id === '65') { row.disposition = 'pending'; row.text = 'QQ long message\n' + '长文本 / long text '.repeat(30); row.segments = [{ type: 'text', text: row.text }]; }
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
        const statusIcon = incoming.getByRole('button', { name: labels.qq.status.pending, exact: true });
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

    test('composer model and reasoning edit the Project across bound conversations', async ({ page, request }, info) => {
      const labels = words(locale, 'personas');
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const model = (await json(request.get('/api/models/profiles'))).find((p: { kind: string }) => p.kind === 'llm');
      const longName = 'QQ external model with a very long display name';
      const created: string[] = [];
      let projectId = '';
      try {
        for (const [name, source] of [[longName, model.source], ['QQ local model', { type: 'local' }], ['QQ unconfigured model', null]] as const) {
          const profile = await json(request.post('/api/models/profiles', { data: {
            name, alias: `qq-composer-${created.length}-${Date.now()}`, kind: 'llm', model_ref: 'fixture', source,
            enabled: name === longName,
          } }));
          created.push(profile.id);
        }
        const project = await json(request.post('/api/projects', { data: {
          kind: 'qqbot', name: 'QQ composer settings', context_policy: {}, bot_account: String(Date.now()),
          websocket_url: 'ws://127.0.0.1:3001', model_profile_id: model.id, access_token: 'keep-token',
          system_prompt: 'Keep this prompt', keywords: ['bot'], reply_message_limit: 3,
        } }));
        projectId = project.id;
        const group = await json(request.post(`/api/projects/${projectId}/sessions`, { data: { title: 'QQ group settings', target_kind: 'group', target_id: '7788' } }));
        const friend = await json(request.post(`/api/projects/${projectId}/sessions`, { data: { title: 'QQ friend settings', target_kind: 'friend', target_id: '12345678901234567890' } }));
        const patches: unknown[] = [], sessionPatches: unknown[] = [];
        page.on('request', (req) => {
          if (req.method() !== 'PATCH') return;
          if (req.url().endsWith(`/api/projects/${projectId}`)) patches.push(req.postDataJSON());
          if (req.url().includes('/api/sessions/')) sessionPatches.push(req.postDataJSON());
        });
        await page.goto(`/projects/${projectId}?session=${group.session_id}`);
        const composer = page.locator('.composer'), menu = page.getByRole('menu');
        const trigger = composer.getByRole('button', { name: labels.model, exact: true });
        await trigger.click();
        await expect(menu.getByRole('menuitemradio', { name: longName, exact: true })).toBeEnabled();
        await expect(menu.getByRole('menuitemradio', { name: 'QQ local model', exact: false })).toHaveCount(0);
        await expect(menu.getByRole('menuitemradio', { name: 'QQ unconfigured model', exact: false })).toHaveCount(0);
        await expect(menu.getByRole('menuitemcheckbox', { name: labels.harness, exact: true })).toHaveCount(0);
        await expect(menu.getByRole('menuitem', { name: labels.harnessSettings, exact: true })).toHaveCount(0);
        const reasoning = menu.getByRole('menuitemcheckbox', { name: labels.reasoning, exact: true });
        await expect(reasoning).toBeChecked();
        await reasoning.click();
        await expect(reasoning).not.toBeChecked();
        await expect(reasoning).toBeEnabled();
        await menu.getByRole('menuitemradio', { name: longName, exact: true }).click();
        await expect(trigger).toHaveText(longName);
        await expect(trigger).toBeEnabled();
        expect(patches).toEqual([{ reasoning: false }, { model_profile_id: created[0] }]);
        expect(sessionPatches).toEqual([]);
        const saved = await json(request.get(`/api/projects/${projectId}`));
        expect(saved).toMatchObject({ model_profile_id: created[0], reasoning: false, system_prompt: 'Keep this prompt', has_access_token: true, keywords: ['bot'], reply_message_limit: 3 });
        for (const session of [group, friend]) {
          expect((await json(request.get(`/api/sessions/${session.session_id}`))).effective)
            .toMatchObject({ model_profile_id: created[0], reasoning: false, harness_enabled: true });
        }
        await openSidebar(page);
        await page.getByRole('button', { name: labels.projectActions.replace('{{name}}', project.name), exact: true }).click();
        await page.getByRole('menuitem', { name: labels.projectSettings, exact: true }).click();
        await expect(page.getByLabel(labels.model, { exact: true })).toContainText(longName);
        await expect(page.getByRole('switch', { name: labels.qq.reasoning, exact: true })).not.toBeChecked();
        await openSidebar(page);
        await page.locator('.session-select').filter({ hasText: friend.title }).click();
        const hint = labels.qq.chattingIn.replace('{{targetId}}', friend.target_id);
        await expect(composer.getByRole('textbox', { name: hint, exact: true })).toHaveAttribute('placeholder', hint);
        await expect(trigger).toHaveText(longName);
        await composer.getByRole('button', { name: labels.qq.pause, exact: true }).click();
        const resume = composer.getByRole('button', { name: labels.qq.resume, exact: true });
        await expect(resume).toBeVisible();
        await expect(resume.locator('svg')).toHaveAttribute('data-icon', 'inline-start');
        await expect(composer.getByRole('button', { name: labels.qq.stop, exact: true }).locator('svg')).toHaveAttribute('data-icon', 'inline-start');
        await trigger.focus();
        await trigger.press('Enter');
        await expect(reasoning).not.toBeChecked();
        await expect(reasoning).toBeEnabled();
        await page.keyboard.press('Escape');
        await expect(trigger).toBeFocused();
        for (const checkWidth of [width === 390 ? 1366 : 390, width]) {
          await page.setViewportSize({ width: checkWidth, height: 900 });
          await expect(composer).toHaveAttribute('data-expanded', String(checkWidth === 390));
          await expect.poll(async () => composer.evaluate((node) => {
            const input = node.querySelector('textarea')!, buttons = Array.from(node.querySelectorAll('button'));
            const text = input.getBoundingClientRect(), style = getComputedStyle(input);
            const first = buttons[0].getBoundingClientRect(), last = buttons.at(-1)!.getBoundingClientRect();
            return node.getAttribute('data-expanded') === 'true'
              ? text.bottom <= first.top + 1
              : text.left + parseFloat(style.paddingLeft) > buttons[1].getBoundingClientRect().right
                && text.right - parseFloat(style.paddingRight) < buttons[2].getBoundingClientRect().left
                && Math.abs(text.y + text.height / 2 - last.y - last.height / 2) < 1;
          })).toBe(true);
          expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
          if (checkWidth === 390) for (const button of await composer.locator('button').all())
            expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(width === 390 ? 44 : 28);
        }
        await page.screenshot({ path: info.outputPath('qq-composer-settings.png') });
        await page.reload();
        await expect(trigger).toHaveText(longName);
        await expect(composer.getByRole('textbox', { name: hint, exact: true })).toBeDisabled();
        await trigger.click();
        await expect(reasoning).not.toBeChecked();
        await page.route('**/api/models/profiles', async (route) => {
          const response = await route.fetch();
          await route.fulfill({ response, json: (await response.json()).filter((profile: { source?: { type: string } }) => profile.source?.type !== 'provider') });
        });
        await page.reload();
        await expect(trigger).toHaveText(labels.unavailable);
        await trigger.click();
        await expect(page.getByRole('menuitemradio')).toHaveCount(0);
        await expect(reasoning).toBeEnabled();
        await expect(reasoning).not.toBeChecked();
        expect(errors).toEqual([]);
      } finally {
        if (projectId) await json(request.delete(`/api/projects/${projectId}`));
        for (const id of created) await json(request.delete(`/api/models/profiles/${id}`));
      }
    });

    test('failed or delayed composer saves preserve confirmed state and subsequent navigation', async ({ page, request }) => {
      const labels = words(locale, 'personas');
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const model = (await json(request.get('/api/models/profiles'))).find((p: { kind: string }) => p.kind === 'llm');
      const projects: string[] = [];
      let release: () => void = () => {};
      try {
        const sessions = [];
        for (let index = 0; index < 2; index++) {
          const project = await json(request.post('/api/projects', { data: {
            kind: 'qqbot', name: `QQ save ${index}`, context_policy: {}, bot_account: `${Date.now()}${index}`,
            websocket_url: 'ws://127.0.0.1:3001', model_profile_id: model.id,
          } }));
          projects.push(project.id);
          sessions.push(await json(request.post(`/api/projects/${project.id}/sessions`, { data: { title: `QQ save conversation ${index}`, target_kind: 'group', target_id: `${index + 1}7788` } })));
        }
        let fail = true, calls = 0;
        const pending = new Promise<void>((resolve) => { release = resolve; });
        await page.route(`**/api/projects/${projects[0]}`, async (route) => {
          if (route.request().method() !== 'PATCH') return route.continue();
          calls++;
          if (fail) return route.fulfill({ status: 500, json: { error: { code: 'SAVE_FAILED', message: 'QQ settings save failed' } } });
          await pending;
          await route.continue();
        });
        await page.goto(`/projects/${projects[0]}?session=${sessions[0].session_id}`);
        const trigger = page.locator('.composer .chat-model-select');
        await trigger.click();
        const reasoning = page.getByRole('menuitemcheckbox', { name: labels.reasoning, exact: true });
        await reasoning.click();
        await expect(page.getByRole('alert')).toContainText('QQ settings save failed');
        await expect(reasoning).toBeChecked();
        await expect(reasoning).toBeEnabled();
        expect((await json(request.get(`/api/projects/${projects[0]}`))).reasoning).toBe(true);
        fail = false;
        await reasoning.click();
        await expect(reasoning).toBeDisabled();
        await expect(trigger).toBeDisabled();
        await expect(page.getByRole('alert')).toHaveCount(0);
        await page.keyboard.press('Escape');
        await expect(page.locator('.composer').getByRole('button', { name: labels.qq.stop, exact: true })).toBeEnabled();
        await openSidebar(page);
        await page.locator(`[data-project-id="${projects[1]}"] .project-select`).click();
        const next = page.locator('.session-select').filter({ hasText: sessions[1].title });
        await expect(next).toBeVisible();
        await next.click();
        await expect(page.getByRole('heading', { name: sessions[1].title, exact: true })).toBeVisible();
        const saved = page.waitForResponse((response) => response.url().endsWith(`/api/projects/${projects[0]}`) && response.request().method() === 'PATCH');
        release();
        await saved;
        expect(calls).toBe(2);
        await expect(page.getByRole('heading', { name: sessions[1].title, exact: true })).toBeVisible();
        await expect(trigger).toBeEnabled();
        await trigger.click();
        await expect(reasoning).toBeChecked();
        await expect(page.getByRole('alert')).toHaveCount(0);
        expect((await json(request.get(`/api/projects/${projects[0]}`))).reasoning).toBe(false);
        expect((await json(request.get(`/api/projects/${projects[1]}`))).reasoning).toBe(true);
      } finally {
        release();
        await page.unrouteAll({ behavior: 'wait' });
        for (const id of projects) await json(request.delete(`/api/projects/${id}`));
      }
    });

    test('reply limit and skip complete normally while missing reply pauses', async ({ page, request }, info) => {
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
        expect(limitedRun.metadata.qq_reply).toEqual({ sent_count: 2, message_limit: 2, limit_reached: true, skipped: false });
        await page.screenshot({ path: info.outputPath('qq-reply-limit.png') });

        const skipped = await json(request.post(`/__test__/qq/${session.session_id}/reply/skip`));
        await expect(page.locator('[data-qq-reply-skipped]')).toHaveText(labels.qq.replySkipped);
        await expect(page.locator('[data-qq-delivery]')).toHaveCount(2);
        await expect(page.getByRole('button', { name: labels.qq.pause, exact: true })).toBeVisible();
        const skippedRun = await json(request.get(`/api/runs/${skipped.run_id}`));
        expect(skippedRun.status).toBe('DONE');
        expect(skippedRun.metadata.qq_reply).toEqual({ sent_count: 0, message_limit: 2, limit_reached: false, skipped: true });
        const skippedBatch = (await json(request.get(`/api/qq/sessions/${session.session_id}/batches`))).items.find((batch: { id: number }) => batch.id === skipped.batch_id);
        expect(skippedBatch.trigger_kind).toBe('followup');
        await page.reload();
        await expect(page.locator('[data-qq-reply-skipped]')).toHaveText(labels.qq.replySkipped);
        await page.screenshot({ path: info.outputPath('qq-skipped-reply.png') });

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
