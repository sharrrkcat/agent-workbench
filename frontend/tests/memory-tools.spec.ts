import { readFileSync } from 'node:fs';
import { expect, test, type Locator, type APIResponse } from '@playwright/test';

const names = ['memory_list', 'memory_search', 'memory_read', 'memory_write', 'memory_forget'];
async function json(response: Promise<APIResponse>) {
  const value = await response;
  expect(value.ok(), await value.text()).toBe(true);
  return value.json();
}
async function groupChecked(root: Locator, checked: boolean) {
  for (const name of names) await expect(root.getByRole('checkbox', { name, exact: true })).toBeChecked({ checked });
}

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  const read = (ns: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${ns}.json`, import.meta.url), 'utf8'));
  const words = read('personas'), memory = read('memory');
  test.describe(`Memory tool group ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: 900 }, hasTouch: width === 390 });
    test('links every switch across defaults, session and composer settings', async ({ page, request }, info) => {
      const errors: string[] = []; page.on('pageerror', (error) => errors.push(error.message));
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const owner = await json(request.post('/api/characters', { data: { kind: 'normal', name: `Memory tools ${locale} ${width}`,
        harness_enabled: true, memory_learning: 'automatic', tools_allowed: ['web_fetch'] } }));
      await page.goto(`/characters/${owner.id}/settings`);
      await page.getByRole('button', { name: words.characterCards.configureTools, exact: true }).click();
      const characterTools = page.getByRole('form', { name: words.tools, exact: true });
      const characterDrawer = page.getByRole('dialog', { name: words.harnessSettings, exact: true });
      await groupChecked(characterTools, true);
      await characterTools.getByRole('checkbox', { name: 'memory_write', exact: true }).click();
      await groupChecked(characterTools, false);
      await expect(characterTools.getByRole('checkbox', { name: 'web_fetch', exact: true })).toBeChecked();
      await characterTools.getByRole('checkbox', { name: 'memory_read', exact: true }).click();
      await groupChecked(characterTools, true);
      await characterTools.getByRole('checkbox', { name: 'memory_forget', exact: true }).click();
      await characterTools.getByRole('button', { name: words.save, exact: true }).click();
      await expect.poll(async () => (await json(request.get(`/api/characters/${owner.id}`))).memory_learning).toBe('manual');
      await characterDrawer.getByRole('button', { name: words.close, exact: true }).click();
      await expect(characterDrawer).toBeHidden();
      await expect(page.getByRole('switch', { name: memory.readEnabled, exact: true })).toBeChecked();
      await page.getByRole('button', { name: memory.automatic, exact: true }).click();
      await page.getByRole('button', { name: words.characterCards.configureTools, exact: true }).click();
      await groupChecked(characterTools, true);
      await expect(characterTools.getByRole('button', { name: words.save, exact: true })).toBeDisabled();
      await expect.poll(async () => (await json(request.get(`/api/characters/${owner.id}`))).memory_learning).toBe('automatic');
      await characterDrawer.getByRole('button', { name: words.close, exact: true }).click();
      await expect(characterDrawer).toBeHidden();

      const session = await json(request.post(`/api/characters/${owner.id}/sessions`, { data: { title: 'Memory tool switches' } }));
      await page.goto(`/characters/${owner.id}?session=${session.session_id}`);
      await page.getByRole('button', { name: words.sessionSettings, exact: true }).click();
      const settings = page.getByRole('dialog', { name: words.sessionSettings, exact: true });
      await groupChecked(settings, true);
      await settings.getByRole('checkbox', { name: 'memory_search', exact: true }).click();
      await groupChecked(settings, false);
      await settings.getByRole('button', { name: words.save, exact: true }).click();
      await expect(settings).toBeHidden();
      const saved = await json(request.get(`/api/sessions/${session.session_id}`));
      expect(saved.overrides.memory_learning).toBe('manual');
      expect(saved.overrides.tools_allowed).toBeUndefined();
      expect(saved.effective.memory_enabled).toBe(true);

      const openTools = async () => {
        await page.locator('.composer .chat-model-select').click();
        await page.getByRole('menuitem', { name: words.harnessSettings, exact: true }).click();
      };
      const sheet = page.getByRole('dialog', { name: words.harnessSettings, exact: true });
      await openTools();
      await groupChecked(sheet, false);
      await sheet.getByRole('checkbox', { name: 'memory_list', exact: true }).click();
      await groupChecked(sheet, true);
      await sheet.getByRole('button', { name: words.save, exact: true }).click();
      await expect(sheet).toBeHidden();
      expect((await json(request.get(`/api/sessions/${session.session_id}`))).overrides.memory_learning).toBe('automatic');
      await openTools();
      const restoreTools = words.restoreInheritanceFor.replace('{{field}}', words.tools);
      await sheet.getByRole('button', { name: restoreTools, exact: true }).click();
      await groupChecked(sheet, true);
      await page.screenshot({ path: info.outputPath('memory-tools.png'), animations: 'disabled' });
      await sheet.getByRole('button', { name: words.save, exact: true }).click();
      await expect(sheet).toBeHidden();
      const restored = await json(request.get(`/api/sessions/${session.session_id}`));
      expect(restored.overrides.memory_learning).toBeUndefined();
      expect(restored.effective.tools_allowed).toEqual(['web_fetch']);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(errors).toEqual([]);
      await request.delete(`/api/characters/${owner.id}`);
    });
  });
}
