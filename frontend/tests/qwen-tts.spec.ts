import { chooseOption, fillCombobox } from './controls';
import fs from 'node:fs';
import { expect, test } from '@playwright/test';

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));
  test(`Qwen Base architecture, defaults and saved controls (${locale})`, async ({ page, request }, info) => {
    await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
    expect((await request.post('/__test__/runtimes', { data: {} })).ok()).toBeTruthy();
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('/settings?tab=models');
    await chooseOption(page.locator('.model-toolbar').getByLabel(labels.kind, { exact: true }), labels.kinds['tts']);
    await page.getByRole('button', { name: labels.addModel, exact: true }).click();
    const dialog = page.getByRole('dialog');
    const reference = dialog.getByLabel(labels.modelRef, { exact: true });
    await expect(dialog.getByLabel(labels.directory.fields.architecture, { exact: true })).toHaveCount(0);
    await expect(dialog.getByLabel(labels.source, { exact: true }).locator('[data-slot="select-value"]')).toHaveText(labels.localRuntime);
    await expect(dialog.getByLabel(labels.source, { exact: true })).toBeDisabled();
    await fillCombobox(reference, 'tts/fixture-qwen');
    await expect(dialog.getByLabel(labels.params.top_k, { exact: true })).toHaveValue('50');
    await expect(dialog.getByLabel(labels.params.temperature, { exact: true })).toHaveValue('0.9');
    await dialog.getByLabel(labels.params.speed, { exact: true }).fill('0.85');
    await chooseOption(dialog.getByLabel(labels.params.response_format, { exact: true }), 'WAV');
    await dialog.getByLabel(labels.params.top_k, { exact: true }).fill('0');
    await fillCombobox(reference, 'tts/fixture-chatterbox');
    await expect(dialog.getByLabel(labels.params.top_k, { exact: true })).toHaveCount(0);
    await expect(dialog.getByLabel(labels.params.temperature, { exact: true })).toHaveValue('0.8');
    await fillCombobox(reference, 'tts/fixture-qwen');
    await expect(dialog.getByLabel(labels.params.top_k, { exact: true })).toHaveValue('50');
    await expect(dialog.getByLabel(labels.params.speed, { exact: true })).toHaveValue('0.85');
    await expect(dialog.getByLabel(labels.params.response_format, { exact: true }).locator('[data-slot="select-value"]')).toHaveText('WAV');
    const alias = `runtime-fixture-qwen-${locale.toLowerCase()}`;
    await dialog.getByLabel(labels.name, { exact: true }).fill(`Qwen Base ${locale}`);
    await dialog.getByLabel(labels.alias, { exact: true }).fill(alias);
    await fillCombobox(dialog.getByLabel(labels.modelRef, { exact: true }), 'tts/fixture-qwen');
    await dialog.getByRole('switch', { name: labels.params.do_sample, exact: true }).uncheck();
    await dialog.getByLabel(labels.params.top_k, { exact: true }).fill('0');
    await dialog.getByLabel(labels.params.max_new_tokens, { exact: true }).fill('512');
    await expect(dialog).toContainText(labels.qwenReferenceHint);
    await page.screenshot({ path: info.outputPath('qwen-profile.png') });
    await dialog.getByRole('button', { name: labels.save, exact: true }).click();
    await expect(dialog).toHaveCount(0);
    const profiles = await (await request.get('/api/models/profiles')).json();
    const saved = profiles.find((profile: { alias: string }) => profile.alias === alias);
    expect(saved.parameters).toEqual({ speed: 0.85, response_format: 'wav', seed: null, do_sample: false,
      temperature: 0.9, top_p: 1, top_k: 0, repetition_penalty: 1.05, max_new_tokens: 512 });
    expect(saved.source.type).toBe('local');
    expect(saved.source.execution_options.device).toBe('cuda');
    const row = page.locator('.model-list .model-row').filter({ hasText: alias });
    await row.getByRole('button', { name: labels.edit, exact: true }).click();
    await expect(dialog.getByRole('group', { name: labels.directory.information, exact: true })).toContainText('qwen3tts');
    await expect(dialog.getByLabel(labels.source, { exact: true })).toBeDisabled();
    await expect(dialog.getByLabel(labels.params.top_k, { exact: true })).toHaveValue('0');
    await expect(dialog.getByRole('switch', { name: labels.params.do_sample, exact: true })).not.toBeChecked();
    await expect(dialog.getByLabel(labels.params.max_new_tokens, { exact: true })).toHaveValue('512');
    expect(errors).toEqual([]);
  });
}
