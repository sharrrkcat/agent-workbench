import { readFileSync } from 'node:fs';
import { expect, test, type APIResponse } from '@playwright/test';
import { answerConfirmation } from './controls';

async function json(response: Promise<APIResponse>) {
  const value = await response;
  expect(value.ok(), await value.text()).toBe(true);
  return value.json();
}

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/personas.json`, import.meta.url), 'utf8'));
  for (const width of [1366, 390]) {
    test.describe(`Chat model menu ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
      test.beforeEach(async ({ page }) => {
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      });

      test('groups sources, saves model selection and fits a long name in the composer', async ({ page, request }, info) => {
        const session = await json(request.post('/__test__/session'));
        const provider = await json(request.post('/api/models/providers', { data: {
          name: 'Menu provider', connection: { base_url: 'https://menu.test/v1' },
        } }));
        const created: string[] = [];
        try {
          const longName = 'Very long model name with a context window and version suffix';
          const remote = await json(request.post('/api/models/profiles', { data: {
            name: longName, alias: `menu-remote-${Date.now()}`, kind: 'llm', model_ref: 'fixture',
            source: { type: 'provider', provider_profile_id: provider.id },
          } }));
          created.push(remote.id);
          const local = await json(request.post('/api/models/profiles', { data: {
            name: 'Local menu model', alias: `menu-local-${Date.now()}`, kind: 'llm', model_ref: 'missing-local-model', enabled: false,
            source: { type: 'local' },
          } }));
          created.push(local.id);
          const unconfigured = await json(request.post('/api/models/profiles', { data: {
            name: 'Unconfigured menu model', alias: `menu-unconfigured-${Date.now()}`, kind: 'llm', model_ref: 'unconfigured', enabled: false,
          } }));
          created.push(unconfigured.id);
          const providerNames = (await json(request.get('/api/models/providers'))).map((item: { name: string }) => item.name);
          await page.goto('/');
          const trigger = page.locator('.composer .chat-model-select');
          const input = page.locator('.composer textarea');
          await input.fill(locale === 'en' ? 'Hi' : '你好');
          await expect(page.locator('.topbar [role=combobox]')).toHaveCount(0);
          await trigger.click();
          const menu = page.getByRole('menu');
          const groups = menu.locator('[data-slot=dropdown-menu-group]');
          await expect(groups).toHaveCount(2);
          await expect(groups.first().locator('[data-slot=dropdown-menu-label]')).toHaveText(['Local', ...providerNames, labels.unconfiguredSource]);
          await expect(menu.getByRole('menuitemradio', { name: 'Local menu model', exact: false })).toBeDisabled();
          await expect(menu.getByRole('menuitemradio', { name: 'resource-embedding', exact: true })).toHaveCount(0);
          await expect(menu.getByRole('menuitem', { name: `${labels.reasoning} ${labels.comingSoon}`, exact: true })).toBeDisabled();
          await menu.getByRole('menuitemradio', { name: longName, exact: true }).click();
          await expect(menu).toBeHidden();
          await expect(trigger).toHaveText(longName);
          expect((await json(request.get(`/api/sessions/${session.session_id}`))).model_profile_id).toBe(remote.id);
          await expect(page.locator('.composer')).toHaveAttribute('data-expanded', 'false');
          const modelBox = (await trigger.boundingBox())!;
          expect(modelBox.width).toBeLessThanOrEqual(width === 390 ? 120 : 160);
          if (width === 390) expect(modelBox.height).toBeGreaterThanOrEqual(44);
          const geometry = await input.evaluate((node) => {
            const box = node.getBoundingClientRect(), style = getComputedStyle(node);
            return { right: box.right - parseFloat(style.paddingRight), center: box.y + box.height / 2 };
          });
          expect(geometry.right).toBeLessThan(modelBox.x);
          expect(Math.abs(geometry.center - modelBox.y - modelBox.height / 2)).toBeLessThan(1);
          expect(await trigger.evaluate((node) => parseFloat(getComputedStyle(node).borderRadius))).toBeGreaterThan(modelBox.height / 2);
          await trigger.focus();
          await trigger.press('Enter');
          await expect(menu.getByRole('menuitemradio', { name: longName, exact: true })).toBeChecked();
          await page.screenshot({ path: info.outputPath('model-menu.png') });
          await page.keyboard.press('Escape');
          await expect(trigger).toBeFocused();
          expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        } finally {
          await request.patch(`/api/sessions/${session.session_id}`, { data: { model_profile_id: session.model_profile_id } });
          for (const id of created) await request.delete(`/api/models/profiles/${id}`);
          await request.delete(`/api/models/providers/${provider.id}`);
        }
      });

      test('Sheet fades in and out on each opening and respects reduced motion', async ({ page, request }) => {
        await request.post('/__test__/session');
        await page.addInitScript(() => {
          (window as any).sheetFades = [];
          document.addEventListener('transitionrun', (event) => {
            if (!(event.target instanceof HTMLElement) || event.target.dataset.slot !== 'sheet-content' || event.propertyName !== 'opacity') return;
            const node = event.target, samples: number[] = [];
            (window as any).sheetFades.push(samples);
            function sample() {
              samples.push(Number(getComputedStyle(node).opacity));
              if (node.getAnimations().some((animation) => animation.playState === 'running')) requestAnimationFrame(sample);
            }
            sample();
          });
        });
        await page.goto('/');
        const sheet = page.getByRole('dialog', { name: labels.harnessSettings, exact: true });
        for (let index = 0; index < 2; index++) {
          await page.locator('.chat-model-select').click();
          await page.getByRole('menuitem', { name: labels.harnessSettings, exact: true }).click();
          await expect(sheet).toBeVisible();
          await expect.poll(() => page.evaluate((n) => (window as any).sheetFades[n]?.at(-1), index * 2)).toBe(1);
          await page.keyboard.press('Escape');
          await expect(sheet).toBeHidden();
          await expect.poll(() => page.evaluate((n) => (window as any).sheetFades[n]?.at(-1), index * 2 + 1)).toBe(0);
        }
        const fades: number[][] = await page.evaluate(() => (window as any).sheetFades);
        for (const [index, values] of fades.entries()) {
          expect(values.some((value) => value > 0 && value < 1)).toBe(true);
          if (index % 2 === 0) expect(values[0]).toBeLessThan(0.5);
          else expect(values[0]).toBeGreaterThan(0.5);
        }
        await page.emulateMedia({ reducedMotion: 'reduce' });
        await page.locator('.chat-model-select').click();
        await page.getByRole('menuitem', { name: labels.harnessSettings, exact: true }).click();
        await expect(sheet).toHaveCSS('transition-property', 'none');
        await expect(page.locator('[data-slot=sheet-overlay]')).toHaveCSS('transition-property', 'none');
      });

      test('Harness toggle and Sheet save, discard and failure preserve session settings', async ({ page, request }, info) => {
        const session = await json(request.post('/__test__/session'));
        await page.goto('/');
        const trigger = page.locator('.chat-model-select');
        await trigger.click();
        const toggle = page.getByRole('menuitemcheckbox', { name: labels.harness, exact: true });
        await expect(toggle).toBeChecked();
        await expect(toggle.locator('[data-slot=dropdown-menu-checkbox-item-indicator]')).toHaveText('on');
        await toggle.click();
        await expect(toggle).not.toBeChecked();
        await expect(toggle.locator('[data-slot=dropdown-menu-checkbox-item-indicator]')).toHaveText('off');
        expect((await json(request.get(`/api/sessions/${session.session_id}`))).tools_allowed).toEqual(session.tools_allowed);
        const settings = page.getByRole('menuitem', { name: labels.harnessSettings, exact: true });
        await settings.focus();
        await settings.press('Enter');
        const sheet = page.getByRole('dialog', { name: labels.harnessSettings, exact: true });
        await expect(sheet).toBeVisible();
        await expect(page.getByRole('menu')).toBeHidden();
        expect((await json(request.get(`/api/sessions/${session.session_id}`))).harness_enabled).toBe(false);
        const readFile = sheet.getByRole('checkbox', { name: 'read_file', exact: true });
        await readFile.uncheck();
        await page.keyboard.press('Escape');
        await answerConfirmation(page, false, locale);
        await expect(readFile).not.toBeChecked();
        await page.keyboard.press('Escape');
        await answerConfirmation(page, true, locale);
        await expect(sheet).toBeHidden();
        await expect(trigger).toBeFocused();
        await trigger.click();
        await settings.click();
        await expect(readFile).toBeChecked();
        await readFile.uncheck();
        await page.screenshot({ path: info.outputPath('harness-sheet.png') });
        const patches: unknown[] = [];
        let fail = true;
        await page.route(`**/api/sessions/${session.session_id}`, async (route) => {
          if (route.request().method() === 'PATCH') {
            patches.push(route.request().postDataJSON());
            if (fail) {
              await route.fulfill({ status: 500, json: { detail: 'Harness save failed' } });
              return;
            }
          }
          await route.continue();
        });
        await sheet.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(sheet.getByRole('alert')).toBeVisible();
        await expect(readFile).not.toBeChecked();
        fail = false;
        await sheet.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(sheet).toBeHidden();
        const saved = await json(request.get(`/api/sessions/${session.session_id}`));
        expect(saved.tools_allowed).toEqual(session.tools_allowed.filter((name: string) => name !== 'read_file'));
        expect(saved.harness_enabled).toBe(false);
        expect(patches).toEqual([{ tools_allowed: saved.tools_allowed }, { tools_allowed: saved.tools_allowed }]);
        await page.getByRole('button', { name: labels.sessionSettings, exact: true }).click();
        const dialog = page.getByRole('dialog', { name: labels.sessionSettings, exact: true });
        await expect(dialog.getByRole('checkbox', { name: 'read_file', exact: true })).toHaveCount(0);
        await dialog.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(dialog).toBeHidden();
        expect(patches.at(-1)).not.toHaveProperty('harness_enabled');
        expect(patches.at(-1)).not.toHaveProperty('tools_allowed');
      });
    });
  }
}

test('no selectable models still exposes Harness without selecting a replacement', async ({ page, request }) => {
  const session = await json(request.post('/__test__/session'));
  await page.route('**/api/models/profiles', (route) => route.fulfill({ json: [] }));
  await page.goto('/');
  const trigger = page.locator('.chat-model-select');
  await expect(trigger).toHaveText('Unavailable');
  await trigger.click();
  await expect(page.getByRole('menuitem', { name: 'Unavailable', exact: true })).toBeDisabled();
  await expect(page.getByRole('menuitemcheckbox', { name: 'Harness', exact: true })).toBeEnabled();
  await expect(page.getByRole('menuitemradio')).toHaveCount(0);
  expect((await json(request.get(`/api/sessions/${session.session_id}`))).model_profile_id).toBe(session.model_profile_id);
});

test('pending configuration blocks sending and a failed toggle keeps the confirmed value', async ({ page, request }) => {
  const session = await json(request.post('/__test__/session'));
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let fail = false;
  await page.route(`**/api/sessions/${session.session_id}`, async (route) => {
    if (route.request().method() === 'PATCH') {
      if (fail) {
        await route.fulfill({ status: 500, json: { error: { code: 'SAVE_FAILED', message: 'Toggle save failed' } } });
        return;
      }
      await gate;
    }
    await route.continue();
  });
  await page.goto('/');
  await page.locator('.composer textarea').fill('Retained draft');
  const send = page.locator('.composer').getByRole('button', { name: 'Send', exact: true });
  await page.locator('.chat-model-select').click();
  const toggle = page.getByRole('menuitemcheckbox', { name: 'Harness', exact: true });
  await toggle.click();
  await expect(toggle).toBeDisabled();
  await expect(toggle).toBeChecked();
  await expect(send).toBeDisabled();
  release();
  await expect(toggle).not.toBeChecked();
  await expect(toggle).toBeEnabled();
  await expect(send).toBeEnabled();
  fail = true;
  await toggle.click();
  await expect(page.locator('.error-banner')).toContainText('Toggle save failed');
  await expect(toggle).not.toBeChecked();
  await expect(page.locator('.composer textarea')).toHaveValue('Retained draft');
});
