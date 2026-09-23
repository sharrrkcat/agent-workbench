import { readFileSync } from 'node:fs';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { answerConfirmation, chooseOption } from './controls';

const words = (locale: string, namespace: string) =>
  JSON.parse(
    readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'),
  );
const png = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j1ioAAAAASUVORK5CYII=',
  'base64',
);

async function bounded(popup: Locator, viewport: { width: number; height: number }) {
  await expect(popup).toBeVisible();
  const rect = await popup.boundingBox();
  expect(rect!.x).toBeGreaterThanOrEqual(0);
  expect(rect!.y).toBeGreaterThanOrEqual(0);
  expect(rect!.x + rect!.width).toBeLessThanOrEqual(viewport.width + 1);
  expect(rect!.y + rect!.height).toBeLessThanOrEqual(viewport.height + 1);
}

async function touchTargets(scope: Locator) {
  await expect
    .poll(() =>
      scope.evaluate((root) =>
        [
          ...root.querySelectorAll<HTMLElement>(
            'button, [role="tab"], [role="option"], input:not([type="hidden"]), textarea',
          ),
        ]
          .filter((element) => {
            if (element.matches('[role="switch"], [role="checkbox"], [aria-hidden="true"]')) return false;
            const rect = element.getBoundingClientRect();
            return (
              rect.width > 0 &&
              rect.height > 0 &&
              (Math.round(rect.width * 1000) < 44000 || Math.round(rect.height * 1000) < 44000)
            );
          })
          .map((element) => ({
            name: element.getAttribute('aria-label') || element.textContent,
            slot: element.dataset.slot,
          })),
      ),
    )
    .toEqual([]);
}

async function openSettings(page: Page, name: string) {
  await page.locator('.session-sidebar').getByRole('button', { name, exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
}

for (const locale of ['en', 'zh-CN']) {
  const common = words(locale, 'common'),
    llm = words(locale, 'llm');
  const settings = words(locale, 'settings'),
    knowledge = words(locale, 'knowledge');
  const personas = words(locale, 'personas'),
    worldbook = words(locale, 'worldbook');
  for (const viewport of [
    { width: 1366, height: 900 },
    { width: 390, height: 844 },
  ]) {
    test.describe(`Mira controls ${locale} ${viewport.width}`, () => {
      test.use({ viewport, hasTouch: viewport.width === 390 });
      test.beforeEach(async ({ page }) => {
        await page.addInitScript((value) => localStorage.setItem('agent-workbench.locale', value), locale);
      });

      test('keyboard tabs, labels, touch targets, dropdowns and bounded dialogs', async ({ page }, info) => {
        const errors: string[] = [];
        page.on('pageerror', (error) => errors.push(error.message));
        await page.goto('/settings?tab=models');
        const profiles = page.getByRole('tab', { name: llm.profiles, exact: true });
        const providers = page.getByRole('tab', { name: llm.providers, exact: true });
        await profiles.focus();
        await profiles.press('ArrowRight');
        await expect(providers).toBeFocused();
        await expect(profiles).toHaveAttribute('aria-selected', 'true');
        await providers.press('Space');
        await expect(providers).toHaveAttribute('aria-selected', 'true');
        await expect(page.getByRole('button', { name: llm.addModel, exact: true })).toHaveCount(0);

        const addProvider = page.getByRole('button', { name: llm.addProvider, exact: true });
        await expect(addProvider).toHaveCSS('height', viewport.width === 390 ? '44px' : '28px');
        await addProvider.click();
        const dialog = page.getByRole('dialog');
        await bounded(dialog, viewport);
        const rect = await dialog.boundingBox();
        expect(rect!.width).toBeLessThanOrEqual(viewport.width === 390 ? 358 : 384);
        const name = dialog.getByLabel(llm.name, { exact: true });
        await dialog.getByText(llm.name, { exact: true }).click();
        await expect(name).toBeFocused();
        await name.fill('Draft provider');
        if (viewport.width === 390) await touchTargets(dialog);
        const close = dialog.getByRole('button', { name: common.close, exact: true });
        await close.focus();
        await page.keyboard.press('Tab');
        await expect(name).toBeFocused();
        await page.keyboard.press('Escape');
        await expect(dialog).toBeHidden();
        await expect(addProvider).toBeFocused();

        const runtime = page.getByRole('tab', { name: llm.localRuntime, exact: true });
        await providers.focus();
        await providers.press('ArrowRight');
        await expect(runtime).toBeFocused();
        await runtime.press('Enter');
        await expect(runtime).toHaveAttribute('aria-selected', 'true');
        const enabled = page.getByRole('switch', { name: llm.enableLocalRuntime, exact: true });
        const label = page.locator('[data-slot="field-label"]').filter({ hasText: llm.enableLocalRuntime });
        const before = await enabled.isChecked();
        await label.click();
        await expect(enabled).toBeChecked({ checked: !before });
        await label.click();
        if (viewport.width === 390) {
          expect((await label.boundingBox())!.height).toBeGreaterThanOrEqual(44);
          expect((await enabled.boundingBox())!.height).toBeLessThan(44);
        }
        await page.locator('.runtime-download-settings > [data-slot="collapsible-trigger"]').click();
        const proxy = page.getByLabel(llm.download.http_proxy, { exact: true });
        await proxy.fill('http://127.0.0.1:8899');
        await providers.click();
        await expect(proxy).toBeHidden();
        await runtime.click();
        await expect(proxy).toHaveValue('http://127.0.0.1:8899');
        await profiles.click();
        const add = page.getByRole('button', { name: llm.addModel, exact: true });
        await add.click();
        await bounded(dialog, viewport);
        expect((await dialog.boundingBox())!.width).toBeLessThanOrEqual(viewport.width === 390 ? 358 : 768);
        const source = dialog.getByLabel(llm.source, { exact: true });
        await source.click();
        const popup = page.getByRole('listbox');
        await bounded(popup, viewport);
        if (viewport.width === 390) await touchTargets(popup);
        await page.getByRole('option', { name: llm.localRuntime, exact: true }).click();
        await expect(source).toBeFocused();
        await expect(dialog.getByLabel(llm.kind, { exact: true })).toBeDisabled();
        const reference = dialog.getByLabel(llm.modelRef, { exact: true });
        await reference.fill('llms/manual-model.gguf');
        await reference.press('Tab');
        await expect(reference).toHaveValue('llms/manual-model.gguf');
        const body = dialog.locator(':scope > .overflow-y-auto');
        await dialog.getByRole('button', { name: llm.save, exact: true }).scrollIntoViewIfNeeded();
        if (viewport.width === 390) {
          expect(await body.evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true);
          await touchTargets(dialog);
        }
        await bounded(dialog, viewport);
        await page.screenshot({ path: info.outputPath('model-controls.png') });
        await page.keyboard.press('Escape');
        await expect(add).toBeFocused();
        expect(errors).toEqual([]);
      });

      test('resource drafts, folded validation, busy navigation and history replay', async ({
        page,
        request,
      }) => {
        await request.post('/__test__/session', { data: {} });
        await page.goto('/');
        await openSettings(page, personas.settings);
        const nav = page.getByRole('navigation', { name: settings.title, exact: true });
        await nav.getByRole('button', { name: settings.knowledge, exact: true }).click();
        const globals = page.getByRole('tab', { name: settings.resources.settings, exact: true });
        const list = page.getByRole('tab', { name: settings.resources.list, exact: true });
        await globals.click();
        const chunk = page.getByLabel(knowledge.chunkSize, { exact: true });
        const original = Number(await chunk.inputValue());
        await chunk.fill(String(original + 1));
        await list.click();
        await expect(chunk).toBeHidden();
        await globals.click();
        await expect(chunk).toHaveValue(String(original + 1));
        const advanced = page.locator('.resource-advanced > [data-slot="collapsible-trigger"]');
        await advanced.click();
        const candidate = page.getByLabel(knowledge.vectorCandidates, { exact: true });
        const originalCandidate = await candidate.inputValue();
        await candidate.fill('');
        await advanced.click();
        const save = page.getByRole('button', { name: common.save, exact: true });
        await save.click();
        await expect(advanced).toHaveAttribute('aria-expanded', 'true');
        await expect(candidate).toBeFocused();
        await candidate.fill(originalCandidate);
        await nav.getByRole('button', { name: settings.general, exact: true }).click();
        await expect(page.getByRole('alertdialog')).toBeVisible();
        await page.evaluate(() => history.back());
        await answerConfirmation(page, false, locale);
        await expect(page).toHaveURL(/\/settings\?tab=knowledge$/);
        await expect(chunk).toHaveValue(String(original + 1));

        let release!: () => void;
        const gate = new Promise<void>((resolve) => {
          release = resolve;
        });
        await page.route('**/api/knowledge/settings', async (route) => {
          if (route.request().method() === 'PATCH') await gate;
          await route.continue();
        });
        const submitted = page.waitForRequest(
          (value) => value.method() === 'PATCH' && value.url().endsWith('/knowledge/settings'),
        );
        await save.click();
        await submitted;
        await expect(chunk).toBeDisabled();
        await nav.getByRole('button', { name: settings.general, exact: true }).click();
        await expect(page).toHaveURL(/\/settings\?tab=knowledge$/);
        await expect(page.getByRole('alertdialog')).toHaveCount(0);
        await page.evaluate(() => history.back());
        await expect(page).toHaveURL(/\/settings\?tab=knowledge$/);
        const saved = page.waitForResponse(
          (value) => value.request().method() === 'PATCH' && value.url().endsWith('/knowledge/settings'),
        );
        release();
        await saved;
        await expect(chunk).toBeEnabled();
        await page.unroute('**/api/knowledge/settings');
        await chunk.fill(String(original + 2));
        const length = await page.evaluate(() => history.length);
        await page.evaluate(() => history.back());
        await expect(page.getByRole('alertdialog')).toBeVisible();
        await expect(page).toHaveURL(/\/settings\?tab=knowledge$/);
        await page.keyboard.press('Escape');
        await expect(page.getByRole('alertdialog')).toBeHidden();
        await expect(chunk).toHaveValue(String(original + 2));
        expect(await page.evaluate(() => history.length)).toBe(length);
        await page.evaluate(() => history.back());
        await answerConfirmation(page, true, locale);
        await expect(page).toHaveURL(/\/$/);
        await page.evaluate(() => history.forward());
        await expect(page).toHaveURL(/\/settings\?tab=knowledge$/);
        await globals.click();
        await expect(chunk).toHaveValue(String(original + 1));
        expect(await page.evaluate(() => history.length)).toBe(length);
        await page.evaluate(() => history.back());
        await expect(page).toHaveURL(/\/$/);
        await page.evaluate(() => history.forward());
        await expect(page).toHaveURL(/\/settings\?tab=knowledge$/);
      });

      test('nested confirmation, focus return and deletion cancellation', async ({ page, request }, info) => {
        const models = await (await request.get('/api/models/profiles')).json();
        const base = await (
          await request.post('/api/knowledge/bases', {
            data: {
              name: `Controls ${locale} ${viewport.width}`,
              embedding_model_profile_id: models.find(
                (item: { alias: string }) => item.alias === 'resource-embedding',
              ).id,
            },
          })
        ).json();
        await page.goto('/settings?tab=knowledge');
        await page
          .getByRole('button', {
            name: settings.resources.manageNamed.replace('{{name}}', base.name),
            exact: true,
          })
          .click();
        const paste = page.getByRole('button', { name: knowledge.pasteText, exact: true });
        await paste.click();
        const dialog = page.locator('[data-slot="dialog-content"]');
        const title = dialog.getByLabel(knowledge.sourceTitle, { exact: true });
        await title.fill('Unsaved source');
        const close = dialog.getByRole('button', { name: common.close, exact: true });
        await close.click();
        const confirmation = page.getByRole('alertdialog');
        await bounded(confirmation, viewport);
        await expect(confirmation.getByRole('button', { name: common.cancel, exact: true })).toBeFocused();
        if (viewport.width === 390) await touchTargets(confirmation);
        await page.screenshot({ path: info.outputPath('nested-confirmation.png') });
        await page.keyboard.press('Escape');
        await expect(confirmation).toBeHidden();
        await expect(title).toHaveValue('Unsaved source');
        await expect(close).toBeFocused();
        await close.click();
        await answerConfirmation(page, true, locale);
        await expect(dialog).toBeHidden();
        await expect(paste).toBeFocused();
        const remove = page
          .locator('.resource-heading')
          .getByRole('button', { name: common.delete, exact: true });
        await remove.click();
        await answerConfirmation(page, false, locale);
        expect((await request.get(`/api/knowledge/bases/${base.id}`)).ok()).toBe(true);
        await expect(remove).toBeFocused();
        await remove.click();
        await answerConfirmation(page, true, locale);
        await expect
          .poll(async () => (await request.get(`/api/knowledge/bases/${base.id}`)).status())
          .toBe(404);
      });

      test('session drafts, IME, attachment preview and collapsed approvals', async ({ page, request }) => {
        const session = await (await request.post('/__test__/session', { data: {} })).json();
        await request.patch(`/api/models/profiles/${session.model_profile_id}`, {
          data: { capabilities: { streaming: true, tools: true, vision: true } },
        });
        await page.goto('/');
        await page.getByRole('button', { name: personas.sessionSettings, exact: true }).click();
        const dialog = page.getByRole('dialog');
        await dialog.getByRole('tab', { name: personas.configuration, exact: true }).click();
        const seed = dialog.getByLabel(llm.params.seed, { exact: true });
        const penalty = dialog.getByLabel(llm.params.presence_penalty, { exact: true });
        const tool = dialog.getByRole('checkbox', { name: 'base64_encode', exact: true });
        await tool.uncheck();
        await seed.fill('0');
        await penalty.fill('');
        await penalty.pressSequentially('-0.2');
        await expect(penalty).toHaveValue('-0.2');
        await dialog.getByRole('tab', { name: personas.members, exact: true }).click();
        await dialog.getByRole('tab', { name: personas.configuration, exact: true }).click();
        await expect(seed).toHaveValue('0');
        await expect(penalty).toHaveValue('-0.2');
        await expect(tool).not.toBeChecked();
        if (viewport.width === 390) {
          const label = dialog.locator('[data-slot="field-label"]').filter({ hasText: /^base64_encode$/ });
          expect((await label.boundingBox())!.height).toBeGreaterThanOrEqual(44);
          expect((await tool.boundingBox())!.height).toBeLessThan(44);
        }
        await tool.check();
        await dialog.getByRole('button', { name: common.save, exact: true }).click();
        await expect(dialog).toBeHidden();
        expect(
          (await (await request.get(`/api/sessions/${session.session_id}`)).json()).generation.seed,
        ).toBe(0);
        expect(
          (await (await request.get(`/api/sessions/${session.session_id}`)).json()).generation.presence_penalty,
        ).toBe(-0.2);
        const composer = page.locator('.composer');
        const input = composer.getByRole('textbox');
        await input.fill('中文输入');
        await input.evaluate((element) =>
          element.dispatchEvent(
            new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true }),
          ),
        );
        expect(await (await request.get(`/api/sessions/${session.session_id}/runs`)).json()).toEqual([]);
        await expect(input).toHaveValue('中文输入');
        await composer
          .locator('input[type="file"]')
          .setInputFiles({ name: 'control.png', mimeType: 'image/png', buffer: png });
        await expect(page.locator('.attachment-chip.upload-ready')).toHaveCount(1);
        const preview = page.getByRole('button', {
          name: personas.previewImage.replace('{{name}}', 'control.png'),
          exact: true,
        });
        await preview.click();
        await bounded(dialog, viewport);
        await expect(dialog.getByRole('img')).toBeVisible();
        await page.keyboard.press('Escape');
        await expect(preview).toBeFocused();
        await page
          .getByRole('button', {
            name: personas.removeAttachment.replace('{{name}}', 'control.png'),
            exact: true,
          })
          .click();
        await expect(page.locator('.attachment-chip')).toHaveCount(0);
        await input.fill('approval');
        await composer.getByRole('button', { name: personas.send, exact: true }).click();
        const reply = page.locator('article[data-run-id]');
        await expect(reply.locator('.processing-toggle')).toHaveAttribute('aria-expanded', 'false');
        const approve = reply.getByRole('button', {
          name: locale === 'en' ? 'Approve' : '批准',
          exact: true,
        });
        await expect(approve).toBeVisible();
        if (viewport.width === 390) await touchTargets(reply);
        await approve.click();
        await expect(reply.locator('.reply-answer')).toHaveText('Browser final answer.');
        await expect(reply.locator('.status-done')).toBeVisible();
      });

      test('worldbook entry controls preserve drafts and tools remain callable', async ({
        page,
        request,
      }) => {
        await request.post('/__test__/session', { data: {} });
        const book = await (
          await request.post('/api/worldbooks', {
            data: { name: `Control book ${locale} ${viewport.width}` },
          })
        ).json();
        const entries = [];
        for (const name of ['First', 'Second'])
          entries.push(
            await (
              await request.post(`/api/worldbooks/${book.id}/entries`, {
                data: { name, keywords_text: 'control', content: `${name} content` },
              })
            ).json(),
          );
        await page.goto('/settings?tab=worldbook');
        await page
          .getByRole('button', {
            name: settings.resources.manageNamed.replace('{{name}}', book.name),
            exact: true,
          })
          .click();
        const first = page.locator(`[data-entry-id="${entries[0].id}"]`);
        await first.getByRole('button', { name: worldbook.expand, exact: true }).click();
        const content = first.getByLabel(worldbook.content, { exact: true });
        await content.fill('Unsaved content');
        await first.getByRole('switch').click();
        await expect(first.getByRole('switch')).not.toBeChecked();
        await expect(first.getByRole('switch')).toBeEnabled();
        await expect(content).toHaveValue('Unsaved content');
        await first.getByRole('button', { name: worldbook.collapse, exact: true }).click();
        await first.getByRole('button', { name: worldbook.expand, exact: true }).click();
        await expect(content).toHaveValue('Unsaved content');
        await first.getByRole('button', { name: common.save, exact: true }).click();
        await expect
          .poll(
            async () => (await (await request.get(`/api/worldbooks/${book.id}/entries`)).json())[0].content,
          )
          .toBe('Unsaved content');
        if (viewport.width === 390) await touchTargets(first);
        await first.getByRole('button', { name: worldbook.collapse, exact: true }).click();
        const second = page.locator(`[data-entry-id="${entries[1].id}"]`);
        const handle = second.getByRole('button', {
          name: worldbook.dragNamed.replace('{{name}}', 'Second'),
          exact: true,
        });
        await handle.focus();
        await handle.press('ArrowUp');
        await expect
          .poll(async () => (await (await request.get(`/api/worldbooks/${book.id}/entries`)).json())[0].id)
          .toBe(entries[1].id);
        await expect(second.getByRole('button', { name: worldbook.expand, exact: true })).toBeVisible();
        await page.getByRole('navigation').getByRole('button', { name: settings.tools, exact: true }).click();
        const args = page.getByLabel(settings.toolArguments, { exact: true });
        await args.fill('{"value":"hi"}');
        await page.getByRole('button', { name: settings.callTool, exact: true }).click();
        await expect(page.locator('.tool-output')).toContainText('aGk=');
        await page
          .getByRole('navigation')
          .getByRole('button', { name: settings.general, exact: true })
          .click();
        const processing = page.getByRole('switch', {
          name: settings.generalFields.showFullProcessing,
          exact: true,
        });
        await processing.check();
        await page.getByRole('button', { name: settings.generalFields.save, exact: true }).click();
        await expect
          .poll(async () => (await (await request.get('/api/settings/general')).json()).show_full_processing)
          .toBe(true);
      });
    });
  }
}

test('busy model save blocks modal exit and unavailable selected models stay selected', async ({
  page,
  request,
}) => {
  await page.addInitScript(() => localStorage.setItem('agent-workbench.locale', 'en'));
  await page.goto('/settings?tab=models');
  await page.getByRole('tab', { name: 'Providers', exact: true }).click();
  await page.getByRole('button', { name: 'Add provider', exact: true }).click();
  const dialog = page.getByRole('dialog');
  const name = dialog.getByLabel('Name', { exact: true });
  await name.fill('Busy provider');
  await dialog.getByLabel('API base URL', { exact: true }).fill('https://provider.test/v1');
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route('**/api/models/providers', async (route) => {
    if (route.request().method() === 'POST') await gate;
    await route.continue();
  });
  const sent = page.waitForRequest(
    (value) => value.method() === 'POST' && value.url().endsWith('/models/providers'),
  );
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await sent;
  await expect(name).toBeDisabled();
  await expect(dialog.getByRole('switch', { name: 'Enabled', exact: true })).toBeDisabled();
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await page.keyboard.press('Escape');
  await expect(dialog).toBeVisible();
  release();
  await expect(dialog).toBeHidden();
  const session = await (await request.post('/__test__/session', { data: {} })).json();
  await page.route('**/api/models/profiles', async (route) => {
    const response = await route.fetch();
    const models = await response.json();
    await route.fulfill({
      response,
      json: models.filter((model: { id: string }) => model.id !== session.model_profile_id),
    });
  });
  await page.goto('/');
  await expect(page.locator('.chat-model-select')).toContainText('Unavailable');
  await expect(page.locator('.chat-model-select')).toBeDisabled();
  await page.getByRole('button', { name: 'Session settings', exact: true }).click();
  await dialog.getByRole('tab', { name: 'Session configuration', exact: true }).click();
  const model = dialog.getByRole('combobox', { name: 'Model', exact: true });
  await expect(model).toContainText('Unavailable');
  await expect(model).toBeDisabled();
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dialog).toBeHidden();
  expect((await (await request.get(`/api/sessions/${session.session_id}`)).json()).model_profile_id).toBe(
    session.model_profile_id,
  );
});
