import fs from 'node:fs';
import { expect, test } from '@playwright/test';

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));
  test(`Qwen Base architecture, defaults and saved controls (${locale})`, async ({ page, request }, info) => {
    await page.addInitScript((value) => localStorage.setItem('agent-workbench.locale', value), locale);
    expect((await request.post('/__test__/runtimes', { data: {} })).ok()).toBeTruthy();
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('/settings?tab=models');
    await page.locator('.model-toolbar').getByLabel(labels.kind, { exact: true }).selectOption('tts');
    await page.getByRole('button', { name: labels.addModel, exact: true }).click();
    const dialog = page.getByRole('dialog');
    const architecture = dialog.getByLabel(labels.params.architecture, { exact: true });
    await expect(architecture).toBeDisabled();
    await dialog.getByLabel(labels.runtimeVariant, { exact: true }).selectOption('python-worker/audio-cuda');
    await expect(architecture).toBeEnabled();
    await expect(architecture).toHaveValue('chatterbox');
    await architecture.selectOption('qwen3tts');
    await expect(dialog.getByLabel(labels.params.top_k, { exact: true })).toHaveValue('50');
    await expect(dialog.getByLabel(labels.params.temperature, { exact: true })).toHaveValue('0.9');
    await dialog.getByLabel(labels.params.speed, { exact: true }).fill('0.85');
    await dialog.getByLabel(labels.params.response_format, { exact: true }).selectOption('wav');
    await dialog.getByLabel(labels.params.top_k, { exact: true }).fill('0');
    await architecture.selectOption('chatterbox');
    await expect(dialog.getByLabel(labels.params.top_k, { exact: true })).toHaveCount(0);
    await expect(dialog.getByLabel(labels.params.temperature, { exact: true })).toHaveValue('0.8');
    await architecture.selectOption('qwen3tts');
    await expect(dialog.getByLabel(labels.params.top_k, { exact: true })).toHaveValue('50');
    await expect(dialog.getByLabel(labels.params.speed, { exact: true })).toHaveValue('0.85');
    await expect(dialog.getByLabel(labels.params.response_format, { exact: true })).toHaveValue('wav');
    const alias = `runtime-fixture-qwen-${locale.toLowerCase()}`;
    await dialog.getByLabel(labels.name, { exact: true }).fill(`Qwen Base ${locale}`);
    await dialog.getByLabel(labels.alias, { exact: true }).fill(alias);
    await dialog.getByLabel(labels.modelRef, { exact: true }).fill('tts/fixture-qwen');
    await dialog.getByLabel(labels.params.do_sample, { exact: true }).uncheck();
    await dialog.getByLabel(labels.params.top_k, { exact: true }).fill('0');
    await dialog.getByLabel(labels.params.max_new_tokens, { exact: true }).fill('512');
    await expect(dialog).toContainText(labels.qwenReferenceHint);
    await page.screenshot({ path: info.outputPath('qwen-profile.png') });
    await dialog.getByRole('button', { name: labels.save, exact: true }).click();
    await expect(dialog).toHaveCount(0);
    const profiles = await (await request.get('/api/models/profiles')).json();
    const saved = profiles.find((profile: { alias: string }) => profile.alias === alias);
    expect(saved.parameters).toEqual({ architecture: 'qwen3tts', speed: 0.85, response_format: 'wav', do_sample: false,
      temperature: 0.9, top_p: 1, top_k: 0, repetition_penalty: 1.05, max_new_tokens: 512 });
    expect(saved.runtime_variant).toBe('audio-cuda');
    const row = page.locator('.model-list .model-row').filter({ hasText: alias });
    await row.getByRole('button', { name: labels.edit, exact: true }).click();
    await expect(architecture).toHaveValue('qwen3tts');
    await dialog.getByLabel(labels.runtimeVariant, { exact: true }).selectOption('python-worker/audio-cuda');
    await expect(architecture).toHaveValue('qwen3tts');
    await expect(dialog.getByLabel(labels.params.top_k, { exact: true })).toHaveValue('0');
    await expect(dialog.getByLabel(labels.params.do_sample, { exact: true })).not.toBeChecked();
    await expect(dialog.getByLabel(labels.params.max_new_tokens, { exact: true })).toHaveValue('512');
    expect(errors).toEqual([]);
  });
}
