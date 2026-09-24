import { navigateSettings } from './controls';
import fs from 'node:fs';
import { expect, test } from '@playwright/test';

for (const locale of ['en', 'zh-CN']) {
  const labels = JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));
  test(`independent provider key editing and local runtime (${locale})`, async ({ page, request }) => {
    await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
    await page.goto('/settings?tab=models');
    await expect(page.locator('.settings-content [role="tablist"]')).toHaveCount(0);
    await navigateSettings(page, labels.title, labels.providers);
    await page.getByRole('button', { name: labels.addProvider, exact: true }).click();
    const dialog = page.getByRole('dialog');
    const name = `External fixture ${locale}`;
    await dialog.getByLabel(labels.name, { exact: true }).fill(name);
    await dialog.getByLabel(labels.baseUrl, { exact: true }).fill('http://127.0.0.1:1234/v1');
    await dialog.getByLabel(labels.apiKey, { exact: true }).fill('fixture-secret');
    await dialog.getByRole('button', { name: labels.save, exact: true }).click();
    await expect(dialog).toHaveCount(0);
    let provider = (await (await request.get('/api/models/providers')).json()).find((item: { name: string }) => item.name === name);
    expect(provider.connection.has_api_key).toBe(true);
    expect(provider.connection).not.toHaveProperty('api_key');
    const row = page.locator('.model-row').filter({ has: page.getByText(name, { exact: true }) });
    await row.getByRole('button', { name: labels.edit, exact: true }).click();
    await expect(dialog.getByLabel(labels.apiKey, { exact: true })).toHaveValue('');
    await expect(dialog.getByLabel(labels.apiKey, { exact: true })).toHaveAttribute('placeholder', labels.keySet);
    await dialog.getByLabel(labels.connection.timeout_seconds, { exact: true }).fill('90');
    const preserved = page.waitForRequest((value) => value.method() === 'PATCH' && value.url().endsWith(`/providers/${provider.id}`));
    await dialog.getByRole('button', { name: labels.save, exact: true }).click();
    expect((await preserved).postDataJSON().connection).not.toHaveProperty('api_key');
    await expect(dialog).toHaveCount(0);
    provider = await (await request.get(`/api/models/providers/${provider.id}`)).json();
    expect(provider.connection.has_api_key).toBe(true);
    expect(provider.connection.timeout_seconds).toBe(90);
    await row.getByRole('button', { name: labels.edit, exact: true }).click();
    await dialog.getByLabel(labels.apiKey, { exact: true }).fill('clear');
    await dialog.getByLabel(labels.apiKey, { exact: true }).fill('');
    await dialog.getByRole('button', { name: labels.save, exact: true }).click();
    await expect(dialog).toHaveCount(0);
    expect((await (await request.get(`/api/models/providers/${provider.id}`)).json()).connection.has_api_key).toBe(false);
    await row.getByRole('button', { name: labels.delete, exact: true }).click();
    await expect(row).toHaveCount(0);
    await navigateSettings(page, labels.title, labels.localRuntime);
    await expect(page.getByRole('switch', { name: labels.enableLocalRuntime })).toBeVisible();
    await expect(page.locator('.runtime-panel').getByRole('button', { name: labels.delete, exact: true })).toHaveCount(0);
  });
}
