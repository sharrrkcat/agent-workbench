import { readFileSync } from 'node:fs';
import { expect, test, type Locator, type APIResponse } from '@playwright/test';

const names = ['memory_list', 'memory_search', 'memory_read', 'memory_write', 'memory_forget'];
async function json(response: Promise<APIResponse>) {
  const value = await response;
  expect(value.ok(), await value.text()).toBe(true);
  return value.json();
}
async function noMemoryControls(root: Locator) {
  for (const name of names) await expect(root.getByRole('checkbox', { name, exact: true })).toHaveCount(0);
}

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  const read = (ns: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${ns}.json`, import.meta.url), 'utf8'));
  const words = read('personas'), memory = read('memory');
  test.describe(`Memory controls ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: 900 }, hasTouch: width === 390 });
    test('uses one inherited memory switch and keeps tool panels independent', async ({ page, request }, info) => {
      const errors: string[] = []; page.on('pageerror', (error) => errors.push(error.message));
      await request.post('/__test__/session');
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      const owner = await json(request.post('/api/characters', { data: { kind: 'normal', name: `Memory ${locale} ${width}`,
        harness_enabled: true, tools_allowed: ['web_fetch'] } }));
      try {
        await page.goto(`/characters/${owner.id}/settings`);
        const toggle = page.getByRole('switch', { name: memory.enabled, exact: true });
        await expect(toggle).toBeChecked();
        await toggle.uncheck();
        await expect.poll(async () => (await json(request.get(`/api/characters/${owner.id}`))).memory_enabled).toBe(false);
        await page.getByRole('button', { name: words.characterCards.configureTools, exact: true }).click();
        const drawer = page.getByRole('dialog', { name: words.harnessSettings, exact: true });
        await noMemoryControls(drawer);
        await expect(drawer.getByRole('checkbox', { name: 'web_fetch', exact: true })).toBeChecked();
        await expect(drawer.getByRole('button', { name: words.save, exact: true })).toBeDisabled();
        await drawer.getByRole('button', { name: words.close, exact: true }).click();
        await expect(drawer).toBeHidden();
        await toggle.check();
        await expect.poll(async () => (await json(request.get(`/api/characters/${owner.id}`))).memory_enabled).toBe(true);
        const session = await json(request.post(`/api/characters/${owner.id}/sessions`, { data: { title: 'Memory controls' } }));
        await page.goto(`/characters/${owner.id}?session=${session.session_id}`);
        await page.getByRole('button', { name: words.sessionSettings, exact: true }).click();
        const settings = page.getByRole('dialog', { name: words.sessionSettings, exact: true });
        await noMemoryControls(settings);
        await settings.getByRole('tab', { name: memory.title, exact: true }).click();
        await settings.getByRole('switch', { name: memory.enabled, exact: true }).uncheck();
        await settings.getByRole('button', { name: words.save, exact: true }).click();
        await expect(settings).toBeHidden();
        const saved = await json(request.get(`/api/sessions/${session.session_id}`));
        expect(saved.overrides.memory_enabled).toBe(false);
        expect(saved.overrides.tools_allowed).toBeUndefined();
        await page.locator('.composer .chat-model-select').click();
        await page.getByRole('menuitem', { name: words.harnessSettings, exact: true }).click();
        const sheet = page.getByRole('dialog', { name: words.harnessSettings, exact: true });
        await noMemoryControls(sheet);
        await sheet.getByRole('checkbox', { name: 'web_fetch', exact: true }).uncheck();
        await sheet.getByRole('button', { name: words.save, exact: true }).click();
        await expect(sheet).toBeHidden();
        expect((await json(request.get(`/api/sessions/${session.session_id}`))).overrides).toMatchObject({ memory_enabled: false, tools_allowed: [] });
        await page.getByRole('button', { name: words.sessionSettings, exact: true }).click();
        await settings.getByRole('tab', { name: memory.title, exact: true }).click();
        await settings.getByRole('button', { name: words.restoreInheritanceFor.replace('{{field}}', memory.enabled), exact: true }).click();
        await expect(settings.getByRole('switch', { name: memory.enabled, exact: true })).toBeChecked();
        await page.screenshot({ path: info.outputPath('memory-controls.png'), animations: 'disabled' });
        await settings.getByRole('button', { name: words.save, exact: true }).click();
        await expect(settings).toBeHidden();
        const restored = await json(request.get(`/api/sessions/${session.session_id}`));
        expect(restored.overrides.memory_enabled).toBeUndefined();
        expect(restored.effective.memory_enabled).toBe(true);
        expect(restored.effective.tools_allowed).toEqual([]);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        expect(errors).toEqual([]);
      } finally { await request.delete(`/api/characters/${owner.id}`); }
    });
  });
}
