import fs from 'node:fs';
import { expect, test } from '@playwright/test';
import { chooseOption, fillCombobox } from './controls';

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));
  for (const width of [1366, 390]) {
    test.describe(`Provider speech ${locale} ${width}`, () => {
      test.use({ viewport: { width, height: 900 }, hasTouch: width === 390 });
      test('voice architecture, defaults and persistence', async ({ page, request }, info) => {
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
        const name = `Speech provider ${locale} ${width}`;
        const response = await request.post('/api/models/providers', { data: { name, connection: { base_url: 'https://speech.test/v1' } } });
        expect(response.ok()).toBeTruthy();
        const provider = await response.json();
        await page.route(`**/api/models/providers/${provider.id}/models`, (route) => route.fulfill({ status: 502,
          json: { error: { code: 'PROVIDER_ERROR', message: 'Discovery unavailable', type: 'model_error' } } }));
        await page.goto('/settings?tab=models&view=tts');
        await page.getByRole('button', { name: labels.addModel, exact: true }).click();
        const dialog = page.getByRole('dialog');
        await chooseOption(dialog.getByLabel(labels.source, { exact: true }), name);
        const architecture = dialog.getByLabel(labels.providerTTS.architecture, { exact: true });
        const voice = () => dialog.getByLabel(labels.providerTTS.voice, { exact: true });
        await expect(voice()).toContainText('alloy');
        await chooseOption(voice(), 'eve');
        const reference = dialog.getByLabel(labels.modelRef, { exact: true });
        await fillCombobox(reference, `speech-${locale.toLowerCase()}-${width}`);
        await chooseOption(architecture, 'Customize');
        await expect(voice()).toHaveValue('eve');
        await voice().fill('custom-voice');
        await chooseOption(architecture, 'grok-voice-latest');
        await expect(voice()).toContainText('alloy');
        await expect(reference).toHaveValue(`speech-${locale.toLowerCase()}-${width}`);
        await chooseOption(architecture, 'Customize');
        await voice().fill('custom-voice');
        await dialog.getByLabel(labels.params.speed, { exact: true }).fill('1.2');
        await chooseOption(dialog.getByLabel(labels.params.response_format, { exact: true }), 'WAV');
        await dialog.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(dialog).toHaveCount(0);
        const profiles = await (await request.get('/api/models/profiles?kind=tts')).json();
        const profile = profiles.find((p: { model_ref: string }) => p.model_ref === `speech-${locale.toLowerCase()}-${width}`);
        expect(profile.parameters).toEqual({ architecture: 'customize', voice: 'custom-voice', speed: 1.2, response_format: 'wav' });
        await page.locator('.model-profile-card').filter({ has: page.getByText(profile.alias, { exact: true }) }).getByRole('button', { name: labels.edit, exact: true }).click();
        await expect(voice()).toHaveValue('custom-voice');
        await expect(dialog.getByLabel(labels.params.speed, { exact: true })).toHaveValue('1.2');
        await page.screenshot({ path: info.outputPath('provider-tts.png') });
        const overflow = await dialog.evaluate((element) => element.scrollWidth > element.clientWidth + 1);
        expect(overflow).toBe(false);
      });
    });
  }
}
