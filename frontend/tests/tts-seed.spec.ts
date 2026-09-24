import { chooseOption, fillCombobox } from './controls';
import fs from 'node:fs';
import { expect, test } from '@playwright/test';

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));
  for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
    test.describe(`Speech seed ${locale} ${viewport.width}`, () => {
      test.use({ viewport, hasTouch: viewport.width === 390 });
      test('save zero, clear seed and reset on architecture changes', async ({ page, request }, info) => {
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
        expect((await request.post('/__test__/runtimes', { data: {} })).ok()).toBeTruthy();
        const errors: string[] = [];
        page.on('pageerror', (error) => errors.push(error.message));
        await page.goto('/settings?tab=models');
        await chooseOption(page.locator('.model-toolbar').getByLabel(labels.kind, { exact: true }), labels.kinds['tts']);
        for (const selected of ['chatterbox', 'qwen3tts']) {
          await page.getByRole('button', { name: labels.addModel, exact: true }).click();
          const dialog = page.getByRole('dialog');
          const selector = dialog.getByLabel(labels.params.architecture, { exact: true });
          const seed = dialog.getByLabel(labels.params.seed, { exact: true });
          await expect(seed).toHaveCount(0);
          await chooseOption(selector, selected === 'chatterbox' ? labels.chatterboxEnglish : labels.qwen3TTSBase);
          await expect(seed).toHaveValue('');
          await expect(seed).toHaveAttribute('min', '0');
          await expect(seed).toHaveAttribute('max', '4294967295');
          await expect(dialog).toContainText(labels.ttsSeedHint);
          const alias = `runtime-fixture-seed-${selected}-${locale.toLowerCase()}-${viewport.width}`;
          await dialog.getByLabel(labels.name, { exact: true }).fill(`Seed ${selected}`);
          await dialog.getByLabel(labels.alias, { exact: true }).fill(alias);
          await fillCombobox(dialog.getByLabel(labels.modelRef, { exact: true }), `tts/fixture-${selected}`);
          await seed.fill('0');
          await seed.scrollIntoViewIfNeeded();
          const overflow = await page.evaluate(() => [...document.querySelectorAll('body, [data-slot="dialog-content"], [data-slot="field-group"]')]
            .filter((node) => node.scrollWidth > node.clientWidth + 1).map((node) => node.className || node.tagName));
          expect(overflow).toEqual([]);
          await page.screenshot({ path: info.outputPath(`${selected}-seed.png`) });
          await dialog.getByRole('button', { name: labels.save, exact: true }).click();
          await expect(dialog).toHaveCount(0);
          const profiles = await (await request.get('/api/models/profiles')).json();
          const saved = profiles.find((profile: { alias: string }) => profile.alias === alias);
          expect(saved.parameters.seed).toBe(0);
          const row = page.locator('.model-list .model-row').filter({ hasText: alias });
          await row.getByRole('button', { name: labels.edit, exact: true }).click();
          await expect(seed).toHaveValue('0');
          await chooseOption(dialog.getByLabel(labels.source, { exact: true }), labels.localRuntime);
          await expect(seed).toHaveValue('0');
          await seed.fill('4294967295');
          await expect(seed).toHaveValue('4294967295');
          await seed.fill('');
          await dialog.getByRole('button', { name: labels.save, exact: true }).click();
          await expect(dialog).toHaveCount(0);
          expect((await (await request.get(`/api/models/profiles/${saved.id}`)).json()).parameters.seed).toBeNull();
          await row.getByRole('button', { name: labels.edit, exact: true }).click();
          await expect(seed).toHaveValue('');
          await seed.fill('123');
          await chooseOption(selector, selected === 'chatterbox' ? labels.qwen3TTSBase : labels.chatterboxEnglish);
          await expect(seed).toHaveValue('');
          await chooseOption(selector, 'Kokoro-82M v1.0 (ONNX)');
          await expect(seed).toHaveCount(0);
          await dialog.getByRole('button', { name: labels.close, exact: true }).click();
          await expect(dialog).toHaveCount(0);
        }
        expect(errors).toEqual([]);
      });
    });
  }
}
