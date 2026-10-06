import { readFileSync } from 'node:fs';
import { test, expect, type APIResponse, type Locator } from '@playwright/test';
import { chooseOption, openSidebar } from './controls';

const words = (locale: string, namespace: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));
async function json(response: Promise<APIResponse>) { const result = await response; expect(result.ok(), await result.text()).toBe(true); return result.json(); }

async function expectColumns(fields: Locator[], columns: number) {
  const boxes = await Promise.all(fields.map(async (field) => { await expect(field).toBeVisible(); return (await field.boundingBox())!; }));
  for (let i = 1; i < boxes.length; i++) {
    if (i < columns) {
      expect(Math.abs(boxes[i].y - boxes[0].y)).toBeLessThan(2);
      expect(boxes[i].x).toBeGreaterThan(boxes[i - 1].x + boxes[i - 1].width);
    } else {
      expect(boxes[i].y).toBeGreaterThan(boxes[0].y + boxes[0].height);
    }
  }
}

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  test.describe(`QQ settings layout ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
    test('shared tabs, compact fields, drafts and validation across panels', async ({ page, request }, info) => {
      const labels = words(locale, 'personas'), models = words(locale, 'llm'), common = words(locale, 'common');
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      page.on('console', (message) => { if (message.text().includes('not focusable')) errors.push(message.text()); });
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const main = (await json(request.get('/api/models/profiles'))).find((p: { kind: string }) => p.kind === 'llm');
      const stamp = Date.now();
      const generator = await json(request.post('/api/models/profiles', { data: { name: 'Layout image model', alias: `qq-layout-${stamp}`,
        kind: 'image_generation', model_ref: 'draw', source: main.source, parameters: {} } }));
      let projectId = '';
      let releaseSave = () => {};
      try {
        await page.goto('/');
        await openSidebar(page);
        await page.locator('.session-sidebar').getByRole('button', { name: labels.newQQBot, exact: true }).click();
        const dialog = page.getByRole('dialog', { name: labels.newQQBot, exact: true });
        const editor = page.locator('.qq-settings');
        const tab = (key: string) => editor.getByRole('tab', { name: labels.qq.tabs[key], exact: true });
        const field = (label: string) => editor.getByLabel(label, { exact: true });
        const panel = (key: string) => editor.locator(`[data-qq-settings-tab="${key}"]`);
        const capture = async (name: string) => {
          expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
          const [width, scrollWidth] = await editor.evaluate((element) => [element.clientWidth, element.scrollWidth]);
          expect(scrollWidth).toBeLessThanOrEqual(width);
          await page.screenshot({ path: info.outputPath(name) });
        };
        await expect(editor.getByRole('tab')).toHaveCount(3);
        await expect(tab('connection')).toHaveAttribute('aria-selected', 'true');
        await expect(panel('reply')).toHaveCount(1);
        await expect(panel('reply')).toBeHidden();
        await expect(editor.getByRole('tabpanel')).toHaveCount(1);
        await tab('connection').focus();
        await page.keyboard.press('ArrowRight');
        await expect(tab('reply')).toBeFocused();
        await expect(tab('connection')).toHaveAttribute('aria-selected', 'true');
        await page.keyboard.press('Enter');
        await expect(tab('reply')).toHaveAttribute('aria-selected', 'true');
        await page.keyboard.press('ArrowRight');
        await page.keyboard.press('Space');
        await expect(tab('images')).toHaveAttribute('aria-selected', 'true');
        await tab('connection').click();
        await field(labels.projectName).fill('QQ layout');
        await field(labels.qq.account).fill(String(stamp));
        await field(labels.qq.token).fill('layout-secret');
        await expectColumns([field(labels.projectName), field(labels.qq.account)], width === 390 ? 1 : 2);
        await expectColumns([field(labels.qq.url), field(labels.qq.token)], width === 390 ? 1 : 2);
        expect((await editor.boundingBox())!.width).toBeLessThanOrEqual(768);
        await editor.getByRole('switch', { name: labels.qq.enabled, exact: true }).focus();
        await page.keyboard.press('Tab');
        await expect(dialog.getByRole('button', { name: labels.createProject, exact: true })).toBeFocused();
        await capture('dialog-connection.png');

        await tab('reply').click();
        await chooseOption(field(labels.model), main.name);
        await expectColumns([field(labels.model), field(labels.defaultAgentPersona)], width === 390 ? 1 : 2);
        const prompt = field(labels.projectPrompt), keywords = field(labels.qq.keywords);
        await expect(prompt).toHaveValue(labels.qq.defaultPrompt);
        for (const [input, rows] of [[prompt, 4], [keywords, 3]] as const) {
          await expect(input).toHaveAttribute('rows', String(rows));
          const height = (await input.boundingBox())!.height;
          await input.fill(Array.from({ length: 30 }, (_, i) => `Line ${i} with enough text to wrap on a phone`).join('\n'));
          expect((await input.boundingBox())!.height).toBe(height);
          expect(await input.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true);
        }
        await prompt.fill('Keep replies brief.');
        await keywords.fill('BOT\n@12345');
        await field(models.params.temperature).fill('0');
        await field(labels.maxMessages).fill('');
        await field(labels.maxChars).fill('12345');
        await expectColumns([field(labels.maxMessages), field(labels.maxChars)], width === 390 ? 1 : 2);
        await expect(editor.getByText(labels.maxMessagesDescription, { exact: true })).toHaveCount(0);
        await editor.getByRole('switch', { name: labels.qq.icebreakerEnabled, exact: true }).click();
        const timing = [field(labels.qq.icebreakerCold), field(labels.qq.icebreakerWait), field(labels.qq.icebreakerCooldown)];
        for (const [i, value] of ['60', '7', '600'].entries()) await timing[i].fill(value);
        await expectColumns(timing, width === 390 ? 1 : 3);
        const body = dialog.locator('.settings-dialog-body');
        await body.evaluate((element) => { element.scrollTop = 0; });
        await expect(tab('reply')).toBeInViewport();
        await expect(dialog.getByRole('button', { name: labels.createProject, exact: true })).toBeInViewport();
        await capture('dialog-reply.png');

        await tab('images').click();
        await editor.getByRole('switch', { name: labels.qq.imageInputEnabled, exact: true }).click();
        await chooseOption(field(labels.qq.imageDescriptionModel), main.name);
        await chooseOption(field(labels.qq.imageGenerationModel), generator.name);
        const size = field(models.imageGeneration.size);
        await size.fill('wide');
        await chooseOption(field(models.imageGeneration.quality), models.imageGeneration.values.high);
        await chooseOption(field(models.imageGeneration.style), models.imageGeneration.values.vivid);
        await expectColumns([size, field(models.imageGeneration.quality), field(models.imageGeneration.style)], width === 390 ? 1 : 3);
        await capture('dialog-images.png');

        // All mounted panels participate in validation, in form order.
        const create = dialog.getByRole('button', { name: labels.createProject, exact: true });
        await tab('connection').click();
        await field(labels.qq.account).fill('0');
        await tab('reply').click();
        await field(labels.qq.replyLimit).fill('21');
        await tab('images').click();
        await create.click();
        await expect(tab('connection')).toHaveAttribute('aria-selected', 'true');
        await expect(field(labels.qq.account)).toBeFocused();
        await field(labels.qq.account).fill(String(stamp));
        await create.click();
        await expect(tab('reply')).toHaveAttribute('aria-selected', 'true');
        await expect(field(labels.qq.replyLimit)).toBeFocused();
        await field(labels.qq.replyLimit).fill('2');
        await create.click();
        await expect(tab('images')).toHaveAttribute('aria-selected', 'true');
        await expect(size).toBeFocused();
        await size.fill('512x512');
        const gate = new Promise<void>((resolve) => { releaseSave = resolve; });
        await page.route('**/api/projects', async (route) => {
          if (route.request().method() === 'POST') await gate;
          await route.continue();
        });
        const created = page.waitForResponse((response) => response.url().endsWith('/api/projects') && response.request().method() === 'POST');
        await create.click();
        await expect(create).toBeDisabled();
        await tab('connection').click();
        await expect(field(labels.projectName)).toBeDisabled();
        await expect(editor.getByRole('switch', { name: labels.qq.enabled, exact: true })).toBeDisabled();
        await tab('reply').click();
        await expect(field(labels.model)).toBeDisabled();
        await expect(editor.getByRole('switch', { name: labels.qq.reasoning, exact: true })).toBeDisabled();
        await expect(editor.getByRole('switch', { name: labels.qq.icebreakerEnabled, exact: true })).toBeDisabled();
        await tab('images').click();
        await expect(field(labels.qq.imageGenerationModel)).toBeDisabled();
        await expect(editor.getByRole('switch', { name: labels.qq.imageInputEnabled, exact: true })).toBeDisabled();
        await dialog.getByRole('button', { name: common.close, exact: true }).click();
        await expect(dialog).toBeVisible();
        releaseSave();
        projectId = (await (await created).json()).id;
        await expect(dialog).toBeHidden();
        await expect(page).toHaveURL(new RegExp(`/projects/${projectId}$`));
        await page.unroute('**/api/projects');
        const header = page.locator('.settings-header');
        await expect(header.getByRole('heading', { name: 'QQ layout', exact: true })).toBeVisible();
        await expect(header.locator('[data-slot="badge"]')).toHaveCount(0);
        await expect(header.getByRole('button', { name: labels.newSession, exact: true })).toHaveCount(0);
        await expect(tab('connection')).toHaveAttribute('aria-selected', 'true');
        const saved = await json(request.get(`/api/projects/${projectId}`));
        expect(saved).toMatchObject({ temperature: 0, context_policy: { max_messages: null, max_chars: 12345 },
          keywords: ['bot', '@12345'], icebreaker_wait_seconds: 7, image_input_enabled: true,
          image_generation_options: { size: '512x512', quality: 'high', style: 'vivid' }, has_access_token: true });
        await expect(field(labels.qq.token)).toHaveValue('');
        await expect(editor.locator('[data-slot="input-group"]').getByRole('button', { name: labels.qq.clearToken, exact: true })).toBeVisible();
        await expectColumns([field(labels.projectName), field(labels.qq.account)], width === 390 ? 1 : 2);
        await capture('page-connection.png');

        await field(labels.projectName).fill('QQ edited layout');
        await tab('reply').click();
        await expect(prompt).toHaveValue('Keep replies brief.');
        await field(labels.maxMessages).fill('0');
        await expectColumns(timing, width === 390 ? 1 : 3);
        if (width === 1366) {
          await page.setViewportSize({ width: 900, height: 900 });
          await expectColumns(timing, 2);
          await page.setViewportSize({ width, height: 900 });
        }
        await page.locator('.settings-scroll').evaluate((element) => { element.scrollTop = 0; });
        await capture('page-reply.png');
        await tab('images').click();
        await expect(size).toHaveValue('512x512');
        await size.fill('1024x1024');
        await capture('page-images.png');
        const save = editor.getByRole('button', { name: labels.save, exact: true });
        await page.route(`**/api/projects/${projectId}`, async (route) => {
          if (route.request().method() === 'PATCH') await route.fulfill({ status: 500, json: { error: { code: 'TEST_FAILURE', message: 'Cross-tab save failure' } } });
          else await route.continue();
        });
        await save.click();
        await expect(editor.getByRole('alert')).toContainText('Cross-tab save failure');
        await tab('connection').click();
        await expect(field(labels.projectName)).toHaveValue('QQ edited layout');
        await tab('reply').click();
        await expect(field(labels.maxMessages)).toHaveValue('0');
        await tab('images').click();
        await expect(size).toHaveValue('1024x1024');
        await page.unroute(`**/api/projects/${projectId}`);
        await save.click();
        await expect(editor.getByRole('status')).toHaveText(labels.projectSaved);
        await expect(save).toBeDisabled();
        expect(await json(request.get(`/api/projects/${projectId}`))).toMatchObject({ name: 'QQ edited layout',
          context_policy: { max_messages: 0 }, image_generation_options: { size: '1024x1024' }, has_access_token: true });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        expect(errors).toEqual([]);
      } finally {
        releaseSave();
        if (projectId) await request.delete(`/api/projects/${projectId}`);
        await request.delete(`/api/models/profiles/${generator.id}`);
      }
    });
  });
}
