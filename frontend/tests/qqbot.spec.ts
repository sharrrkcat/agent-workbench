import { readFileSync } from 'node:fs';
import { test, expect, type APIResponse } from '@playwright/test';
import { chooseOption, openSidebar } from './controls';

const words = (locale: string, namespace: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));
async function json(response: Promise<APIResponse>) { const value = await response; expect(value.ok(), await value.text()).toBe(true); return value.json(); }

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  test.describe(`QQBot ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
    test('creation, immutable binding, settings and read-only conversation controls', async ({ page, request }, info) => {
      const labels = words(locale, 'personas'), runs = words(locale, 'runs');
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
        await dialog.getByLabel(labels.projectName, { exact: true }).fill('QQ browser');
        await dialog.getByLabel(labels.qq.account, { exact: true }).fill(account);
        await dialog.getByLabel(labels.qq.token, { exact: true }).fill('fixture-secret');
        await chooseOption(dialog.getByLabel(labels.model, { exact: true }), model.name);
        await expect(dialog.getByLabel(labels.model, { exact: true })).toContainText(model.name);
        await expect(dialog.getByLabel(labels.defaultAgentPersona, { exact: true })).toContainText(labels.qq.noPersona);
        await expect(dialog.getByRole('switch', { name: labels.qq.enabled, exact: true })).not.toBeChecked();
        await dialog.getByLabel(labels.qq.keywords, { exact: true }).fill('BOT\nhello');
        await dialog.getByLabel(labels.qq.batchLimit, { exact: true }).fill('3');
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
        await expect(dialog).toBeHidden();
        await expect(page).toHaveURL(new RegExp(`/projects/${projectId}$`));
        await expect(page.getByLabel(labels.qq.token, { exact: true })).toHaveValue('');
        await page.getByLabel(labels.projectPrompt, { exact: true }).fill('Project prompt');
        await page.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(page.getByRole('button', { name: labels.save, exact: true })).toBeDisabled();
        expect((await json(request.get(`/api/projects/${projectId}`))).has_access_token).toBe(true);
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
        await expect(page.locator('textarea')).toHaveCount(0);
        if (width === 390) await expect(page.locator('.session-sidebar')).toBeHidden();
        await json(request.post(`/__test__/qq/${session.session_id}`));
        await expect(page.getByText('qq-fixture bot', { exact: false })).toBeVisible();
        await expect(page.getByText('QQ participant (9999)', { exact: false }).first()).toBeVisible();
        await page.getByRole('button', { name: labels.qq.older, exact: true }).click();
        await expect(page.getByText('Record 1[图片]', { exact: true })).toBeVisible();
        await expect(page.getByRole('button', { name: labels.qq.older, exact: true })).toBeDisabled();
        await page.getByRole('button', { name: labels.qq.latest, exact: true }).click();
        await page.getByRole('button', { name: labels.qq.pause, exact: true }).click();
        await expect(page.getByRole('button', { name: labels.qq.resume, exact: true })).toBeVisible();
        await page.getByRole('button', { name: labels.qq.resume, exact: true }).click();
        await page.getByRole('button', { name: labels.qq.stop, exact: true }).click();
        await expect(page.getByRole('button', { name: labels.qq.resume, exact: true })).toBeVisible();
        await page.getByRole('tab', { name: labels.qq.deliveries, exact: true }).click();
        await expect(page.getByText('Confirmed QQ reply', { exact: true })).toBeVisible();
        await expect(page.getByText(labels.qq.externalId + ': 9001', { exact: true })).toBeVisible();
        await page.getByRole('tab', { name: labels.qq.batches, exact: true }).click();
        await page.getByRole('button', { name: labels.qq.inspectRun, exact: true }).click();
        const details = page.getByRole('dialog', { name: labels.qq.inspectRun, exact: true });
        await expect(details.getByText('Internal QQ prose', { exact: true })).toBeVisible();
        await details.getByRole('button', { name: runs.context.details, exact: true }).click();
        await expect(page.getByRole('dialog').last()).toBeVisible();
        await page.keyboard.press('Escape');
        await page.keyboard.press('Escape');
        await page.screenshot({ path: info.outputPath('qq-conversation.png') });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight)).toBe(true);
        expect(errors).toEqual([]);
      } finally {
        if (projectId) await json(request.delete(`/api/projects/${projectId}`));
      }
    });
  });
}
