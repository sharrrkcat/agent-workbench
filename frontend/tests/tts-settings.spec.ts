import { expect, test } from '@playwright/test';

for (const locale of ['en', 'zh-CN']) {
  for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
    test.describe(`TTS ${locale} ${viewport.width}`, () => {
      test.use({ viewport });
      test('configure ONNX TTS, reopen voices and retain format', async ({ page, request }, info) => {
        await page.addInitScript((locale) => localStorage.setItem('agent-workbench.locale', locale), locale);
        await page.goto('/settings?tab=models');
        await page.locator('.model-toolbar').getByRole('combobox').selectOption('tts');
        await page.getByRole('button', { name: locale === 'en' ? 'Add model' : '添加模型', exact: true }).click();
        const dialog = page.getByRole('dialog');
        await expect(dialog.getByLabel(locale === 'en' ? 'Runtime variant' : '运行环境变体', { exact: true })).toHaveValue('onnx-cpu');
        const alias = `tts-${locale.toLowerCase()}-${viewport.width}`;
        await dialog.getByLabel(locale === 'en' ? 'Name' : '名称', { exact: true }).fill('Kokoro ONNX');
        await dialog.getByLabel(locale === 'en' ? 'Public alias' : '公开别名', { exact: true }).fill(alias);
        await dialog.getByLabel(locale === 'en' ? 'Model reference' : '模型引用', { exact: true }).fill('tts/kokoro');
        await dialog.getByLabel(locale === 'en' ? 'Audio format' : '音频格式', { exact: true }).selectOption('wav');
        await dialog.getByLabel(locale === 'en' ? 'Speech speed' : '语速', { exact: true }).fill('0.85');
        await dialog.getByRole('button', { name: locale === 'en' ? 'Save' : '保存', exact: true }).click();
        await expect(dialog).toHaveCount(0);
        const profile = (await (await request.get('/api/models/profiles?kind=tts')).json()).find((p: { alias: string }) => p.alias === alias);
        expect(profile.parameters).toEqual({ architecture: 'kokoro', speed: 0.85, response_format: 'wav' });
        await page.locator('.model-list .model-row').filter({ hasText: alias }).getByRole('button', { name: locale === 'en' ? 'Edit' : '编辑', exact: true }).click();
        await expect(dialog.locator('.tts-voices-list code')).toHaveCount(54);
        await expect(dialog.locator('.tts-voices-list')).toContainText('zf_xiaobei');
        await expect(dialog.getByLabel(locale === 'en' ? 'Audio format' : '音频格式', { exact: true })).toHaveValue('wav');
        await dialog.locator('.tts-voices-list').scrollIntoViewIfNeeded();
        const overflow = await page.evaluate(() => [...document.querySelectorAll('body, .app-modal-panel, .model-form, .tts-voices-list')]
          .filter((node) => node.scrollWidth > node.clientWidth + 1).map((node) => node.className || node.tagName));
        expect(overflow).toEqual([]);
        await page.screenshot({ path: info.outputPath('tts-settings.png') });
      });
    });
  }
}
