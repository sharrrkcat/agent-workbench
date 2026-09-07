import { expect, test, type Page } from '@playwright/test';

async function runtimeView(page: Page, locale: string) {
  await page.goto('/settings?tab=models');
  const scanned = page.waitForResponse((response) => response.url().endsWith('/api/models/runtimes/storage'));
  await page.getByRole('tab', { name: locale === 'en' ? 'Runtimes' : '运行环境', exact: true }).click();
  await scanned;
  await expect(page.locator('.runtime-storage')).toHaveAttribute('aria-busy', 'false');
}

async function noRuntimeOverflow(page: Page) {
  const overflow = await page.evaluate(() => [...document.querySelectorAll('body, .settings-page, .settings-content, .runtime-panel, .runtime-storage, .runtime-row, .app-modal-panel, .runtime-gpu-mode')]
    .filter((node) => node.scrollWidth > node.clientWidth + 1).map((node) => node.className || node.tagName));
  expect(overflow).toEqual([]);
}

for (const locale of ['en', 'zh-CN']) {
  for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
    test.describe(`runtime ${locale} ${viewport.width}`, () => {
      test.use({ viewport });
      test.beforeEach(async ({ page, request }) => {
        await page.addInitScript((locale) => localStorage.setItem('agent-workbench.locale', locale), locale);
        expect((await request.post('/__test__/runtimes', { data: {} })).ok()).toBeTruthy();
      });

      test('storage details, clear confirmation and preserved installation', async ({ page, request }, info) => {
        await runtimeView(page, locale);
        await page.locator('.runtime-storage-details summary').click();
        await expect(page.locator('.runtime-storage-table')).toContainText('.cache');
        await expect(page.locator('.runtime-storage-table')).toContainText('py/torch-cpu/1.0.0');
        await noRuntimeOverflow(page);
        await page.screenshot({ path: info.outputPath('runtime-storage.png') });
        const clean = locale === 'en' ? 'Clear cache' : '清空缓存';
        await page.locator('.runtime-cache-actions').getByRole('button', { name: clean, exact: true }).click();
        const dialog = page.getByRole('dialog');
        await expect(dialog).toContainText(locale === 'en' ? 'Estimated reclaimable cache' : '缓存预计可释放');
        await dialog.getByRole('button', { name: locale === 'en' ? 'Close' : '关闭', exact: true }).click();
        expect(await (await request.get('/api/models/runtimes/jobs')).json()).toEqual([]);
        await page.locator('.runtime-cache-actions').getByRole('button', { name: clean, exact: true }).click();
        await page.getByRole('dialog').getByRole('button', { name: clean, exact: true }).click();
        await expect(page.locator('.runtime-cache-task')).toContainText(locale === 'en' ? 'Completed' : '已完成');
        await expect(page.locator('.runtime-storage-summary').locator('dd').nth(1)).toHaveText('0 B');
        expect((await (await request.post('/__test__/runtimes/files')).json()).installed_preserved).toBe(true);
        const jobs = await (await request.get('/api/models/runtimes/jobs')).json();
        expect(jobs[0].runtime_id).toBeNull();
        expect(jobs[0].result.after.logical_bytes).toBe(0);
        await noRuntimeOverflow(page);
        await page.screenshot({ path: info.outputPath('cache-cleared.png') });
      });

      test('CUDA automatic and manual values save and reopen', async ({ page, request }, info) => {
        await page.goto('/settings?tab=models');
        await page.getByRole('button', { name: locale === 'en' ? 'Add model' : '添加模型', exact: true }).click();
        const dialog = page.getByRole('dialog');
        await dialog.getByLabel(locale === 'en' ? 'Name' : '名称', { exact: true }).fill('Runtime fixture CUDA');
        const alias = `runtime-fixture-${locale.toLowerCase()}-${viewport.width}`;
        await dialog.getByLabel(locale === 'en' ? 'Public alias' : '公开别名', { exact: true }).fill(alias);
        await dialog.getByLabel(locale === 'en' ? 'Backend' : '推理后端', { exact: true }).selectOption('managed');
        await dialog.getByLabel(locale === 'en' ? 'Runtime variant' : '运行环境变体', { exact: true }).selectOption('cuda');
        await dialog.getByLabel(locale === 'en' ? 'Model reference' : '模型引用', { exact: true }).fill('llms/fixture.gguf');
        const automatic = locale === 'en' ? 'Automatic' : '自动';
        const manual = locale === 'en' ? 'Manual' : '手动';
        const group = dialog.locator('.runtime-gpu-mode');
        await expect(group.getByRole('button', { name: automatic, exact: true })).toHaveAttribute('aria-pressed', 'true');
        await expect(dialog.getByLabel(locale === 'en' ? 'GPU layers' : 'GPU 层数', { exact: true })).toHaveCount(0);
        await group.getByRole('button', { name: manual, exact: true }).click();
        await dialog.getByLabel(locale === 'en' ? 'GPU layers' : 'GPU 层数', { exact: true }).fill('7');
        await group.getByRole('button', { name: automatic, exact: true }).click();
        await group.getByRole('button', { name: manual, exact: true }).click();
        await expect(dialog.getByLabel(locale === 'en' ? 'GPU layers' : 'GPU 层数', { exact: true })).toHaveValue('7');
        await group.getByRole('button', { name: automatic, exact: true }).click();
        await noRuntimeOverflow(page);
        await page.screenshot({ path: info.outputPath('cuda-automatic.png') });
        await dialog.getByRole('button', { name: locale === 'en' ? 'Save' : '保存', exact: true }).click();
        await expect(dialog).toHaveCount(0);
        let profile = (await (await request.get('/api/models/profiles')).json()).find((value: { alias: string }) => value.alias === alias);
        expect(profile.runtime_options.gpu_layers).toBe('auto');
        const row = page.locator('.model-list .model-row').filter({ hasText: alias });
        await row.getByRole('button', { name: locale === 'en' ? 'Edit' : '编辑', exact: true }).click();
        await page.getByRole('dialog').locator('.runtime-gpu-mode').getByRole('button', { name: manual, exact: true }).click();
        await page.getByRole('dialog').getByLabel(locale === 'en' ? 'GPU layers' : 'GPU 层数', { exact: true }).fill('3');
        await page.getByRole('dialog').getByRole('button', { name: locale === 'en' ? 'Save' : '保存', exact: true }).click();
        await expect(page.getByRole('dialog')).toHaveCount(0);
        profile = (await (await request.get('/api/models/profiles')).json()).find((value: { alias: string }) => value.alias === alias);
        expect(profile.runtime_options.gpu_layers).toBe(3);
      });
    });
  }
}

test('cache task cancellation and failure release installation controls', async ({ page, request }) => {
  await page.addInitScript(() => localStorage.setItem('agent-workbench.locale', 'en'));
  await request.post('/__test__/runtimes', { data: { slow: true } });
  await runtimeView(page, 'en');
  await page.getByRole('button', { name: 'Prune cache', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Cancel task', exact: true })).toBeVisible();
  const cudaRow = page.locator('.runtime-row').filter({ has: page.locator('code').filter({ hasText: /^cuda$/ }) });
  await expect(cudaRow.getByRole('button', { name: 'Install runtime', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Cancel task', exact: true }).click();
  await expect(page.locator('.runtime-cache-task')).toContainText('Cancelled');
  await expect(cudaRow.getByRole('button', { name: 'Install runtime', exact: true })).toBeEnabled();
  await request.post('/__test__/runtimes', { data: { fail: true } });
  await page.reload();
  await page.getByRole('tab', { name: 'Runtimes', exact: true }).click();
  await page.getByRole('button', { name: 'Prune cache', exact: true }).click();
  await expect(page.locator('.runtime-cache-task')).toContainText('RUNTIME_CLEANUP_FAILED');
  await expect(cudaRow.getByRole('button', { name: 'Install runtime', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Prune cache', exact: true }).click();
  await expect(page.locator('.runtime-cache-task')).toContainText('Completed');
});

test('incomplete and failed storage scans never appear as zero', async ({ page, request }) => {
  await page.addInitScript(() => localStorage.setItem('agent-workbench.locale', 'en'));
  const snapshot = await (await request.post('/__test__/runtimes', { data: {} })).json();
  const unknown = { complete: false, file_count: null, logical_bytes: null, unique_bytes: null, shared_bytes: null, exclusive_bytes: null };
  await page.route('**/api/models/runtimes/storage', async (route) => {
    await route.fulfill({ json: { ...snapshot, complete: false, totals: unknown,
      groups: snapshot.groups.map((group: { id: string }) => group.id === '.cache' ? { ...group, ...unknown } : group) } });
  });
  await runtimeView(page, 'en');
  await expect(page.locator('.runtime-storage-warning')).toBeVisible();
  await expect(page.locator('.runtime-storage-summary')).toContainText('Unknown');
  expect(await page.locator('.runtime-storage-summary').innerText()).not.toContain('0 B');
  await page.unroute('**/api/models/runtimes/storage');
  await page.route('**/api/models/runtimes/storage', (route) => route.fulfill({ status: 500, json: { error: { message: 'Fixture scan failure' } } }));
  await page.locator('.runtime-panel > .model-toolbar').getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.locator('.runtime-storage')).toContainText('Fixture scan failure');
  await expect(page.locator('.runtime-storage-summary')).toContainText('Unknown');
});
