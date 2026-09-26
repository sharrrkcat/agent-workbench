import { backToChat, fillCombobox } from './controls';
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
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
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

      test('local image hint follows the saved normalized request setting', async ({ page, request }) => {
        const settingsPath = '/api/models/settings';
        const original = await (await request.get(settingsPath)).json();
        const session = await configure(request);
        const created = await request.post('/api/models/profiles', { data: {
          name: 'Request limit hint', alias: `limit-hint-${locale.toLowerCase()}-${width}`, kind: 'llm',
          model_ref: 'llms/fixture', source: { type: 'local' }, capabilities: { vision: true },
        } });
        expect(created.ok()).toBeTruthy();
        const model = await created.json();
        try {
          expect((await request.patch(`/api/sessions/${session.session_id}`, { data: { model_profile_id: model.id } })).ok()).toBeTruthy();
          expect((await request.patch(settingsPath, { data: { max_normalized_request_mb: 128 } })).ok()).toBeTruthy();
          await page.goto('/');
          const picker = page.locator('.composer input[type=file]');
          await picker.setInputFiles(file('limit.png'));
          await expect(page.locator('.composer-hint')).toHaveText(labels.localImageLimit.replace('{{limit}}', '128'));
          await page.goto('/settings?tab=models&view=service');
          const normalized = page.getByRole('spinbutton', { name: llm.normalizedBodyLimit, exact: true });
          await expect(normalized).toHaveValue('128');
          const saved = page.waitForResponse((response) =>
            response.url().endsWith(settingsPath) && response.request().method() === 'PATCH',
          );
          await normalized.fill('256');
          await normalized.press('Enter');
          expect((await saved).ok()).toBeTruthy();
          await expect(normalized).toBeEnabled();
          await backToChat(page);
          await picker.setInputFiles(file('updated-limit.png'));
          await expect(page.locator('.composer-hint')).toHaveText(labels.localImageLimit.replace('{{limit}}', '256'));
          expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
        } finally {
          await request.patch(settingsPath, { data: { max_normalized_request_mb: original.max_normalized_request_mb } });
          await request.delete(`/api/sessions/${session.session_id}`);
          await request.delete(`/api/models/profiles/${model.id}`);
        }
      });

      test('directories detect projectors, retain Vision choices and allow ambiguous drafts', async ({ page, request }, info) => {
        await page.goto('/settings?tab=models');
        await page.getByRole('button', { name: llm.inventory, exact: true }).click();
        const inventoryRow = page.locator('.model-row').filter({ has: page.getByText('llms/fixture', { exact: true }) });
        await expect(inventoryRow).toHaveCount(1);
        await inventoryRow.getByRole('button', { name: llm.addModel, exact: true }).click();
        const dialog = page.getByRole('dialog');
        await expect(dialog.getByLabel(llm.source, { exact: true }).locator('[data-slot="select-value"]')).toHaveText(llm.localRuntime);
        const reference = dialog.getByLabel(llm.modelRef, { exact: true });
        const vision = dialog.getByRole('switch', { name: llm.cap.vision, exact: true });
        const details = dialog.getByRole('group', { name: llm.directory.information, exact: true });
        await expect(reference).toHaveValue('llms/fixture');
        await expect(details).toContainText('llms/fixture/model.gguf');
        await expect(details).toContainText('llms/fixture/mmproj-fixture.gguf');
        await expect(vision).toBeChecked();
        await expect(details.getByRole('combobox')).toHaveCount(0);
        await page.screenshot({ path: info.outputPath('projector.png') });
        const alias = `runtime-fixture-gguf-${locale.toLowerCase()}-${width}`;
        await dialog.getByLabel(llm.alias, { exact: true }).fill(alias);
        await vision.uncheck();
        await dialog.getByRole('button', { name: llm.save, exact: true }).click();
        await expect(dialog).toHaveCount(0);
        const saved = (await (await request.get('/api/models/profiles')).json()).find((profile: { alias: string }) => profile.alias === alias);
        expect(saved.model_ref).toBe('llms/fixture');
        expect(saved.source.execution_options).not.toHaveProperty('mmproj_ref');
        await page.locator('.model-row').filter({ hasText: alias }).getByRole('button', { name: llm.edit, exact: true }).click();
        await expect(details).toContainText('llms/fixture/mmproj-fixture.gguf');
        await expect(vision).not.toBeChecked();
        await fillCombobox(reference, 'llms/other');
        await expect(vision).toBeChecked();
        await fillCombobox(reference, 'llms/text-only');
        await expect(vision).toBeDisabled();
        await expect(vision).not.toBeChecked();
        await fillCombobox(reference, 'llms/ambiguous');
        await expect(details).toContainText(llm.directory.diagnostics.ambiguous_model);
        await dialog.getByRole('button', { name: llm.save, exact: true }).click();
        await expect(dialog).toHaveCount(0);
        expect((await (await request.get(`/api/models/profiles/${saved.id}`)).json()).model_ref).toBe('llms/ambiguous');
        await page.locator('.model-row').filter({ hasText: alias }).getByRole('button', { name: llm.edit, exact: true }).click();
        await fillCombobox(reference, 'llms/transformers');
        await expect(vision).toBeEnabled();
        await expect(details).toContainText(llm.engines.transformers);
        await expect(details.getByText(llm.directory.fields.projector, { exact: true })).toHaveCount(0);
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
