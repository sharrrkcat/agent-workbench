import { chooseOption, fillCombobox } from './controls';
import fs from 'node:fs';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j1ioAAAAASUVORK5CYII=', 'base64');
const file = (name: string) => ({ name, mimeType: 'image/png', buffer: png });

async function configure(request: APIRequestContext) {
  const session = await (await request.post('/__test__/session', { data: {} })).json();
  expect((await request.patch(`/api/models/profiles/${session.model_profile_id}`, { data: {
    capabilities: { vision: true, tools: true, streaming: true },
  } })).ok()).toBeTruthy();
  expect((await request.patch(`/api/sessions/${session.session_id}`, { data: { harness_enabled: false } })).ok()).toBeTruthy();
  return session;
}

async function transfer(page: Page, method: 'paste' | 'drop', name: string) {
  await page.evaluate(({ method, name, bytes }) => {
    const data = new DataTransfer();
    data.items.add(new File([new Uint8Array(bytes)], name, { type: 'image/png' }));
    const event = method === 'paste' ? new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true })
      : new DragEvent('drop', { dataTransfer: data, bubbles: true, cancelable: true });
    document.querySelector(method === 'paste' ? '.composer textarea' : '.composer-wrap')!.dispatchEvent(event);
  }, { method, name, bytes: [...png] });
}

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/personas.json`, import.meta.url), 'utf8'));
  const llm = JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));
  for (const width of [1366, 390]) {
    test.describe(`images ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
      test.beforeEach(async ({ page }) => {
        await page.addInitScript((value) => localStorage.setItem('agent-workbench.locale', value), locale);
      });

      test('select, paste, drop, preview and image-only history', async ({ page, request }, info) => {
        const session = await configure(request);
        await page.goto('/');
        await expect(page.locator('.composer').getByRole('button', { name: labels.attach, exact: true })).toBeEnabled();
        const picker = page.locator('.composer input[type=file]');
        await picker.setInputFiles(file('selected.png'));
        await transfer(page, 'paste', 'pasted.png');
        await transfer(page, 'drop', 'dropped.png');
        await expect(page.locator('.attachment-chip.upload-ready')).toHaveCount(3);
        await page.locator('.attachment-thumbnail').first().click();
        await expect(page.getByRole('dialog').locator('.image-preview')).toBeVisible();
        expect(await page.locator('.image-preview').evaluate((node) => node.clientWidth)).toBeGreaterThan(160);
        await page.screenshot({ path: info.outputPath('preview.png') });
        await page.getByRole('dialog').getByRole('button', { name: labels.close, exact: true }).click();
        await page.getByRole('button', { name: labels.removeAttachment.replace('{{name}}', 'pasted.png'), exact: true }).click();
        await expect(page.locator('.attachment-chip')).toHaveCount(2);
        await expect(page.locator('.composer').getByRole('button', { name: /^(Send|发送)$/, exact: true })).toBeEnabled();
        await page.screenshot({ path: info.outputPath('composer.png') });
        await page.locator('.composer').getByRole('button', { name: /^(Send|发送)$/, exact: true }).click();
        await expect(page.locator('.message-images img')).toHaveCount(2);
        await expect(page.locator('.attachment-chip')).toHaveCount(0);
        await expect(page.locator('.status-done')).toBeVisible();
        await request.patch(`/api/sessions/${session.session_id}`, { data: { context_policy: { mode: 'selected_message' } } });
        await page.reload();
        await expect(page.locator('.message-images img')).toHaveCount(2);
        await expect(page.locator('.message-images img').first()).toHaveJSProperty('naturalWidth', 1);
        expect(await page.locator('.message-images img').first().evaluate((node) => node.clientWidth)).toBeGreaterThan(100);
        await page.locator('.message-images button').first().click();
        await expect(page.getByRole('dialog').locator('.image-preview')).toBeVisible();
        await page.keyboard.press('Escape');
        const history = await (await request.get(`/api/sessions/${session.session_id}/messages`)).json();
        const user = history.find((message: { role: string }) => message.role === 'user');
        expect(user.parts).toEqual([]);
        expect(user.metadata.attachments).toHaveLength(2);
        await page.locator('.message-row.user').getByRole('button', { name: labels.selectContext, exact: true }).click();
        await expect(page.locator('.composer-context').getByRole('combobox')).toContainText('selected.png');
        await page.locator('.composer textarea').fill('Follow up on the images');
        await page.locator('.composer').getByRole('button', { name: /^(Send|发送)$/, exact: true }).click();
        await expect(page.locator('.status-done')).toHaveCount(2);
        expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
        await page.screenshot({ path: info.outputPath('history.png') });
      });

      test('projector selection is editable and resets with model or vision', async ({ page }, info) => {
        await page.route('**/api/models/inventory*', (route) => route.fulfill({ json: [{
          kind: 'llm', name: 'fixture.gguf', model_ref: 'llms/fixture.gguf', state: 'unavailable', error_code: 'MODEL_UNAVAILABLE',
          mmproj_refs: ['llms/mmproj-fixture.gguf'],
        }] }));
        await page.goto('/settings?tab=models');
        await page.getByRole('button', { name: llm.addModel, exact: true }).click();
        const dialog = page.getByRole('dialog');
        await chooseOption(dialog.getByLabel(llm.source, { exact: true }), llm.localRuntime);
        await fillCombobox(dialog.getByLabel(llm.modelRef, { exact: true }), 'llms/fixture.gguf');
        await dialog.getByRole('switch', { name: llm.cap.vision, exact: true }).check();
        const projector = dialog.getByLabel(llm.mmprojRef, { exact: true });
        await projector.press('ArrowDown');
        await page.getByRole('option', { name: 'llms/mmproj-fixture.gguf', exact: true }).click();
        await expect(projector).toHaveValue('llms/mmproj-fixture.gguf');
        await page.screenshot({ path: info.outputPath('projector.png') });
        await fillCombobox(dialog.getByLabel(llm.modelRef, { exact: true }), 'llms/other.gguf');
        await expect(projector).toHaveValue('');
        await fillCombobox(projector, 'llms/manual.gguf');
        await dialog.getByRole('switch', { name: llm.cap.vision, exact: true }).uncheck();
        await expect(projector).toHaveCount(0);
        await dialog.getByRole('switch', { name: llm.cap.vision, exact: true }).check();
        await expect(projector).toHaveValue('');
        await fillCombobox(dialog.getByLabel(llm.modelRef, { exact: true }), 'llms/transformers');
        await expect(dialog.getByRole('switch', { name: llm.cap.vision, exact: true })).toBeEnabled();
        await expect(projector).toHaveCount(0);
        expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
      });
    });
  }
}

test('partial upload failure preserves successes and late results stay in their session', async ({ page, request }) => {
  await configure(request);
  let release!: () => void;
  let started!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const inFlight = new Promise<void>((resolve) => { started = resolve; });
  await page.route('**/api/attachments', async (route) => {
    const data = route.request().postDataBuffer()?.toString() || '';
    if (data.includes('failed.png')) return route.fulfill({ status: 400, json: { error: { code: 'INVALID_ATTACHMENTS', message: 'Fixture upload failure' } } });
    if (data.includes('late.png')) { started(); await gate; }
    await route.continue();
  });
  await page.goto('/');
  await expect(page.locator('.composer').getByRole('button', { name: 'Attach file', exact: true })).toBeEnabled();
  const picker = page.locator('.composer input[type=file]');
  await picker.setInputFiles([file('good.png'), file('failed.png')]);
  await expect(page.locator('.upload-ready')).toHaveCount(1);
  await expect(page.locator('.upload-error')).toHaveCount(1);
  await expect(page.locator('.composer').getByRole('button', { name: /^(Send|发送)$/, exact: true })).toBeEnabled();
  await picker.setInputFiles(file('late.png'));
  await inFlight;
  await expect(page.locator('.upload-uploading [role=status]')).toBeVisible();
  await page.locator('.sidebar-header').getByRole('button', { name: 'New session', exact: true }).click();
  await expect(page.locator('.attachment-chip')).toHaveCount(0);
  const response = page.waitForResponse((value) => value.url().endsWith('/api/attachments'));
  release();
  await (await response).finished();
  await expect(page.locator('.attachment-chip')).toHaveCount(0);
  await picker.setInputFiles(file('fresh.png'));
  await expect(page.locator('.upload-ready')).toHaveCount(1);
  await expect(page.locator('.attachment-strip')).toContainText('fresh.png');
});

test('image capability and attachment policy provide clear prompts', async ({ page, request }) => {
  const session = await configure(request);
  await request.patch(`/api/models/profiles/${session.model_profile_id}`, { data: { capabilities: { streaming: true, tools: true, vision: false } } });
  await page.goto('/');
  await expect(page.locator('.composer').getByRole('button', { name: 'Attach file', exact: true })).toBeEnabled();
  await page.locator('.composer input[type=file]').setInputFiles(file('image.png'));
  await expect(page.locator('.composer-warning')).toContainText('does not support images');
  await expect(page.locator('.composer').getByRole('button', { name: /^(Send|发送)$/, exact: true })).toBeDisabled();
  await request.patch(`/api/sessions/${session.session_id}`, { data: { context_policy: { mode: 'session', include_attachments: 'none' } } });
  await page.reload();
  await expect(page.locator('.composer').getByRole('button', { name: 'Attach file', exact: true })).toBeEnabled();
  await page.locator('.composer input[type=file]').setInputFiles(file('image.png'));
  await expect(page.locator('.composer-warning')).toContainText('Enable Include attachments');
});
