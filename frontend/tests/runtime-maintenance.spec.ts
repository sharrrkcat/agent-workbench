import { navigateModelSettings, chooseOption, fillCombobox, navigateSettings } from './controls';
import { expect, test, type Page } from '@playwright/test';
import fs from 'node:fs';

const words = (locale: string) => JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/llm.json`, import.meta.url), 'utf8'));

async function runtimeView(page: Page, locale: string) {
  await page.goto('/settings?tab=models');
  await navigateModelSettings(page, 'localRuntime');
  await expect(page.getByRole('group', { name: words(locale).coreRuntime, exact: true })).toBeVisible();
}

async function scanStorage(page: Page, locale: string) {
  const scanned = page.waitForResponse((response) => response.url().endsWith('/api/models/local-runtime/storage'));
  await page.getByRole('button', { name: words(locale).storage.scan, exact: true }).click();
  await scanned;
  await expect(page.locator('.runtime-storage')).toHaveAttribute('aria-busy', 'false');
}

async function clearCache(page: Page, locale: string) {
  await page.getByRole('button', { name: words(locale).cacheActions, exact: true }).click();
  await page.getByRole('menuitem', { name: words(locale).cacheClean, exact: true }).click();
}

async function noRuntimeOverflow(page: Page) {
  const overflow = await page.evaluate(() => [...document.querySelectorAll('body, .settings-page, .settings-content, .runtime-panel, .runtime-storage, .runtime-package, [data-slot="dialog-content"], .runtime-gpu-mode')]
    .filter((node) => node.scrollWidth > node.clientWidth + 1).map((node) => node.className || node.tagName));
  expect(overflow).toEqual([]);
}

for (const locale of ['en', 'zh-CN']) {
  for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
    test.describe(`runtime ${locale} ${viewport.width}`, () => {
      test.use({ viewport, hasTouch: viewport.width === 390 });
      test.beforeEach(async ({ page, request }) => {
        await page.addInitScript((locale) => localStorage.setItem('cogita.locale', locale), locale);
        expect((await request.post('/__test__/runtimes', { data: {} })).ok()).toBeTruthy();
      });

      test('storage details, clear confirmation and preserved installation', async ({ page, request }, info) => {
        const labels = words(locale);
        let scans = 0;
        page.on('request', (request) => { if (request.url().endsWith('/api/models/local-runtime/storage')) scans++; });
        await runtimeView(page, locale);
        await expect(page.locator('.runtime-storage-empty')).toContainText(labels.storage.notScanned);
        expect(scans).toBe(0);
        const cards = await page.locator('.runtime-package').evaluateAll((nodes) => nodes.map((node) => {
          const { x, y, width } = node.getBoundingClientRect(); return { x, y, width };
        }));
        expect(cards).toHaveLength(2);
        expect(cards[0].width).toBeCloseTo(cards[1].width, 0);
        expect(cards[0].x).toBe(cards[1].x);
        expect(cards[1].y).toBeGreaterThan(cards[0].y);
        await noRuntimeOverflow(page);
        await page.screenshot({ path: info.outputPath('runtime-cards.png'), animations: 'disabled' });
        await scanStorage(page, locale);
        await page.locator('.runtime-storage-details > [data-slot="collapsible-trigger"]').click();
        await expect(page.locator('.runtime-storage-table')).toContainText('.cache');
        await expect(page.locator('.runtime-storage-table')).toContainText('local/1.0.0');
        await noRuntimeOverflow(page);
        await page.screenshot({ path: info.outputPath('runtime-storage.png'), animations: 'disabled' });
        const clean = locale === 'en' ? 'Clear cache' : '清空缓存';
        await clearCache(page, locale);
        const dialog = page.getByRole('alertdialog');
        await expect(dialog).toContainText(labels.storage.reclaimable);
        await dialog.getByRole('button', { name: locale === 'en' ? 'Cancel' : '取消', exact: true }).click();
        expect(await (await request.get('/api/models/local-runtime/jobs')).json()).toEqual([]);
        await clearCache(page, locale);
        await page.getByRole('alertdialog').getByRole('button', { name: clean, exact: true }).click();
        await expect(page.locator('.runtime-cache-task')).toContainText(locale === 'en' ? 'Completed' : '已完成');
        await expect(page.locator('.runtime-storage')).toContainText(labels.storage.stale);
        expect(scans).toBe(1);
        await expect(page.locator('.runtime-storage-summary').locator('dd').nth(1)).not.toHaveText('0 B');
        await scanStorage(page, locale);
        await expect(page.locator('.runtime-storage-summary').locator('dd').nth(1)).toHaveText('0 B');
        await expect(page.locator('.runtime-storage')).not.toContainText(labels.storage.stale);
        expect((await (await request.post('/__test__/runtimes/files')).json()).installed_preserved).toBe(true);
        const jobs = await (await request.get('/api/models/local-runtime/jobs')).json();
        expect(jobs[0]).not.toHaveProperty('backend_profile_id');
        expect(jobs[0].version).toBeNull();
        expect(jobs[0].result.after.logical_bytes).toBe(0);
        await page.locator('.runtime-cache-task').getByRole('button', { name: labels.runtimeDetails, exact: true }).click();
        await expect(page.getByRole('dialog').locator('.runtime-cache-result')).toContainText('0 B');
        await page.keyboard.press('Escape');
        expect(scans).toBe(2);
        await noRuntimeOverflow(page);
        await page.screenshot({ path: info.outputPath('cache-cleared.png'), animations: 'disabled' });
        await page.getByRole('button', { name: labels.dismissRuntimeResult, exact: true }).click();
        await expect(page.locator('.runtime-cache-task')).toHaveCount(0);
        await page.getByRole('button', { name: labels.refreshRuntimeStatus, exact: true }).click();
        await expect(page.getByRole('button', { name: labels.refreshRuntimeStatus, exact: true })).toBeEnabled();
        await expect(page.locator('.runtime-cache-task')).toHaveCount(0);
        expect(scans).toBe(2);
        await page.reload();
        await expect(page.getByRole('group', { name: labels.coreRuntime, exact: true })).toBeVisible();
        await expect(page.locator('.runtime-cache-task')).toHaveCount(0);
        await expect(page.locator('.runtime-storage-empty')).toContainText(labels.storage.notScanned);
        expect(scans).toBe(2);
        await page.locator('.runtime-task-history > [data-slot="collapsible-trigger"]').click();
        await expect(page.locator('.runtime-history')).toContainText(labels.runtimeOperations.cache_clean);
        await page.locator('.runtime-history').getByRole('button', { name: labels.runtimeLog, exact: true }).first().click();
        await expect(page.getByRole('dialog').locator('.runtime-cache-result')).toContainText('0 B');
      });

      test('installed version and manual repair remain available after a catalog update', async ({ page }, info) => {
        await page.route('**/api/models/local-runtime', (route) => route.fulfill({ json: {
          version: '0.9.0', state: 'installed',
          updated_at: '2026-09-22T00:00:00Z',
        } }));
        await page.route('**/api/models/local-runtime/components', (route) => route.fulfill({ json: [{
          component_id: 'dlss5nr', version: '0.1.1', bundled_version: '0.1.1', state: 'installed', error_code: null,
        }] }));
        await page.route('**/api/models/local-runtime/jobs', (route) => route.fulfill({ json: [
          { id: 'base-complete', component_id: null, version: '0.9.0', operation: 'install', state: 'completed', stage: 'completed', revision: 1, created_at: '2026-09-22T00:00:00Z' },
          { id: 'dlss-complete', component_id: 'dlss5nr', version: '0.1.1', operation: 'install', state: 'completed', stage: 'completed', revision: 1, created_at: '2026-09-22T00:00:01Z' },
        ] }));
        await runtimeView(page, locale);
        const labels = words(locale);
        const row = page.getByRole('group', { name: labels.coreRuntime, exact: true });
        await expect(row.locator('[data-slot="card-title"] [data-slot="badge"]')).toHaveText(['0.9.0', 'windows', 'x86_64']);
        await expect(page.locator('.runtime-package')).toHaveCount(2);
        for (const card of await page.locator('.runtime-package').all()) {
          await expect(card).not.toContainText(labels.jobStates.completed);
          await expect(card.getByRole('button', { name: labels.runtimeDetails, exact: true })).toHaveCount(0);
        }
        await page.screenshot({ path: info.outputPath('installed-runtime-cards.png'), animations: 'disabled' });
        await expect(row.getByRole('button', { name: labels.installRuntime, exact: true })).toHaveCount(0);
        await row.getByRole('button', { name: labels.runtimeActions, exact: true }).click();
        await expect(page.getByRole('menuitem', { name: labels.repairRuntime, exact: true })).toBeEnabled();
        await page.keyboard.press('Escape');
        await expect(row.getByRole('button', { name: labels.runtimeActions, exact: true })).toBeFocused();
        await noRuntimeOverflow(page);
      });

      test('CUDA automatic and manual values save and reopen', async ({ page, request }, info) => {
        await page.goto('/settings?tab=models&view=llm');
        await page.getByRole('button', { name: locale === 'en' ? 'Add model' : '添加模型', exact: true }).click();
        const dialog = page.getByRole('dialog');
        await dialog.getByLabel(locale === 'en' ? 'Name' : '名称', { exact: true }).fill('Runtime fixture CUDA');
        const alias = `runtime-fixture-${locale.toLowerCase()}-${viewport.width}`;
        await dialog.getByLabel(locale === 'en' ? 'Public alias' : '公开别名', { exact: true }).fill(alias);
        await chooseOption(dialog.getByLabel(locale === 'en' ? 'Model source' : '模型来源', { exact: true }), locale === 'en' ? 'Local Runtime' : '本地运行环境');
        await fillCombobox(dialog.getByLabel(locale === 'en' ? 'Model reference' : '模型引用', { exact: true }), 'llms/fixture');
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
        await page.screenshot({ path: info.outputPath('cuda-automatic.png'), animations: 'disabled' });
        await dialog.getByRole('button', { name: locale === 'en' ? 'Save' : '保存', exact: true }).click();
        await expect(dialog).toHaveCount(0);
        let profile = (await (await request.get('/api/models/profiles')).json()).find((value: { alias: string }) => value.alias === alias);
        expect(profile.source.execution_options.gpu_layers).toBe('auto');
        const row = page.locator('.models-panel > .settings-view:not([hidden]) .model-list .model-profile-card').filter({ hasText: alias });
        await row.getByRole('button', { name: locale === 'en' ? 'Edit' : '编辑', exact: true }).click();
        await page.getByRole('dialog').locator('.runtime-gpu-mode').getByRole('button', { name: manual, exact: true }).click();
        await page.getByRole('dialog').getByLabel(locale === 'en' ? 'GPU layers' : 'GPU 层数', { exact: true }).fill('3');
        await page.getByRole('dialog').getByRole('button', { name: locale === 'en' ? 'Save' : '保存', exact: true }).click();
        await expect(page.getByRole('dialog')).toHaveCount(0);
        profile = (await (await request.get('/api/models/profiles')).json()).find((value: { alias: string }) => value.alias === alias);
        expect(profile.source.execution_options.gpu_layers).toBe(3);
      });
    });
  }
}

test('cache task cancellation and failure release installation controls', async ({ page, request }) => {
  await page.addInitScript(() => localStorage.setItem('cogita.locale', 'en'));
  await request.post('/__test__/runtimes', { data: { slow: true } });
  await runtimeView(page, 'en');
  await page.getByRole('button', { name: 'Prune unused cache', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Cancel task', exact: true })).toBeVisible();
  const installation = page.getByRole('group', { name: 'Core Runtime', exact: true });
  await expect(installation.getByRole('button', { name: 'Install', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Cancel task', exact: true }).click();
  await expect(page.locator('.runtime-cache-task')).toContainText('Cancelled');
  await expect(installation.getByRole('button', { name: 'Install', exact: true })).toBeEnabled();
  await request.post('/__test__/runtimes', { data: { fail: true } });
  await page.reload();
  await expect(page).toHaveURL('/settings?tab=models&view=localRuntime');
  await page.getByRole('button', { name: 'Prune unused cache', exact: true }).click();
  await expect(page.locator('.runtime-cache-task')).toContainText('RUNTIME_CLEANUP_FAILED');
  await expect(installation.getByRole('button', { name: 'Install', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Prune unused cache', exact: true }).click();
  await expect(page.locator('.runtime-cache-task')).toContainText('Completed');
});

test('incomplete and failed storage scans never appear as zero', async ({ page, request }) => {
  await page.addInitScript(() => localStorage.setItem('cogita.locale', 'en'));
  const snapshot = await (await request.post('/__test__/runtimes', { data: {} })).json();
  const unknown = { complete: false, file_count: null, logical_bytes: null, unique_bytes: null, shared_bytes: null, exclusive_bytes: null };
  await page.route('**/api/models/local-runtime/storage', async (route) => {
    await route.fulfill({ json: { ...snapshot, complete: false, totals: unknown,
      groups: snapshot.groups.map((group: { id: string }) => group.id === '.cache' ? { ...group, ...unknown } : group) } });
  });
  await runtimeView(page, 'en');
  await scanStorage(page, 'en');
  await expect(page.locator('.runtime-storage-warning')).toBeVisible();
  await expect(page.locator('.runtime-storage-summary')).toContainText('Unknown');
  expect(await page.locator('.runtime-storage-summary').innerText()).not.toContain('0 B');
  await page.unroute('**/api/models/local-runtime/storage');
  await page.route('**/api/models/local-runtime/storage', (route) => route.fulfill({ status: 500, json: { error: { message: 'Fixture scan failure' } } }));
  await scanStorage(page, 'en');
  await expect(page.locator('.runtime-storage')).toContainText('Fixture scan failure');
  await expect(page.locator('.runtime-storage-summary')).toContainText('Unknown');
});

test('status refresh, navigation, reconnect and download settings never scan storage', async ({ page }) => {
  let scans = 0, settingsReads = 0, catalogReads = 0, connections = 0;
  let disconnect = () => {};
  await page.routeWebSocket('**/api/models/events', (socket) => {
    connections++;
    disconnect = () => socket.close();
  });
  page.on('request', (request) => {
    if (request.url().endsWith('/api/models/local-runtime/storage')) scans++;
    if (request.method() === 'GET' && request.url().endsWith('/api/models/local-runtime/settings')) settingsReads++;
    if (request.url().endsWith('/api/models/local-runtime/catalog')) catalogReads++;
  });
  await runtimeView(page, 'en');
  await expect(page.getByRole('button', { name: 'Refresh status', exact: true })).toBeEnabled();
  expect(scans).toBe(0);
  disconnect();
  await expect.poll(() => connections).toBe(2);
  await expect(page.getByRole('button', { name: 'Refresh status', exact: true })).toBeEnabled();
  expect(scans).toBe(0);
  await page.getByRole('button', { name: 'Refresh status', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Refresh status', exact: true })).toBeEnabled();
  expect(scans).toBe(0);
  await scanStorage(page, 'en');
  const snapshot = await page.locator('.runtime-storage-summary dd').allTextContents();
  await navigateSettings(page, 'Providers & Runtime', 'Model Providers');
  await navigateSettings(page, 'Providers & Runtime', 'Local Runtime');
  await expect(page.locator('.runtime-storage-summary dd')).toHaveText(snapshot);
  expect(scans).toBe(1);
  await page.getByRole('button', { name: 'Download settings', exact: true }).click();
  for (const label of await page.locator('.runtime-download-settings [data-slot="field-label"]').all()) {
    await expect(label).toHaveCSS('font-size', '12px');
    await expect(label).toHaveCSS('font-weight', '500');
  }
  await page.getByLabel('HTTP proxy', { exact: true }).fill('http://127.0.0.1:8899');
  const reads = { settingsReads, catalogReads };
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('Settings saved', { exact: true })).toBeVisible();
  await expect(page.getByText('Settings saved', { exact: true })).toHaveCSS('font-size', '12px');
  await expect(page.getByText('Settings saved', { exact: true })).toHaveCSS('font-weight', '400');
  expect({ settingsReads, catalogReads }).toEqual(reads);
  expect(scans).toBe(1);
});

test('leaving clears terminal feedback and entering adopts only running cache tasks', async ({ page, request }) => {
  await request.post('/__test__/runtimes', { data: { slow: true } });
  let scans = 0;
  page.on('request', (request) => { if (request.url().endsWith('/api/models/local-runtime/storage')) scans++; });
  await runtimeView(page, 'en');
  await page.getByRole('button', { name: 'Prune unused cache', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Cancel task', exact: true })).toBeVisible();
  await navigateSettings(page, 'Providers & Runtime', 'Model Providers');
  await expect.poll(async () => (await (await request.get('/api/models/local-runtime/jobs')).json())[0].state).toBe('completed');
  await navigateSettings(page, 'Providers & Runtime', 'Local Runtime');
  await expect(page.locator('.runtime-cache-task')).toHaveCount(0);
  const started = await (await request.post('/api/models/local-runtime/cache/cleanup', { data: { mode: 'prune' } })).json();
  await expect(page.locator('.runtime-cache-task')).toContainText('Prune unused cache');
  await page.reload();
  await expect(page.getByRole('button', { name: 'Cancel task', exact: true })).toBeVisible();
  await expect(page.locator('.runtime-cache-task')).toContainText('Completed');
  expect((await (await request.get(`/api/models/local-runtime/jobs/${started.id}`)).json()).state).toBe('completed');
  expect(scans).toBe(0);
});

test('cache can be cleared before scanning and first scan failure stays distinct from empty storage', async ({ page, request }) => {
  await request.post('/__test__/runtimes', { data: {} });
  await runtimeView(page, 'en');
  await clearCache(page, 'en');
  await expect(page.getByRole('alertdialog')).toContainText('Not scanned yet');
  await page.getByRole('alertdialog').getByRole('button', { name: 'Clear cache', exact: true }).click();
  await expect(page.locator('.runtime-cache-task')).toContainText('Completed');
  await expect(page.locator('.runtime-storage-summary')).toHaveCount(0);
  await page.route('**/api/models/local-runtime/storage', (route) => route.fulfill({ status: 500, json: { error: { message: 'Cannot scan fixture' } } }));
  await scanStorage(page, 'en');
  await expect(page.locator('.runtime-storage')).toContainText('Cannot scan fixture');
  await expect(page.locator('.runtime-storage-empty')).toContainText('Storage statistics unavailable');
  await expect(page.locator('.runtime-storage-empty')).not.toContainText('Not scanned yet');
  await expect(page.locator('.runtime-storage-summary')).toHaveCount(0);
});

test('repair, update, prerequisites and task actions have one primary entry', async ({ page }) => {
  let state = 'broken';
  await page.route('**/api/models/local-runtime', (route) => route.fulfill({ json: {
    version: '1.0.0', state, error_code: state === 'broken' ? 'RUNTIME_BROKEN' : null,
  } }));
  await page.route('**/api/models/local-runtime/components', (route) => route.fulfill({ json: [{
    component_id: 'dlss5nr', version: '0.1.0', bundled_version: '0.1.1', state: 'installed', error_code: null,
  }] }));
  await runtimeView(page, 'en');
  const core = page.getByRole('group', { name: 'Core Runtime', exact: true });
  const component = page.getByRole('group', { name: 'DLSS NR', exact: true });
  await expect(core.getByRole('button', { name: 'Repair', exact: true })).toBeEnabled();
  await expect(core).toContainText('RUNTIME_BROKEN');
  await expect(component.getByRole('button', { name: 'Update', exact: true })).toBeDisabled();
  await expect(component).toContainText('Install or repair Core Runtime first.');
  await core.getByRole('button', { name: 'More actions', exact: true }).click();
  await expect(page.getByRole('menuitem', { name: 'Repair', exact: true })).toHaveCount(0);
  await page.keyboard.press('Escape');
  state = 'installed';
  await page.getByRole('button', { name: 'Refresh status', exact: true }).click();
  await expect(component.getByRole('button', { name: 'Update', exact: true })).toBeEnabled();
  await expect(core.getByRole('button', { name: 'Repair', exact: true })).toHaveCount(0);
  await expect(core).not.toContainText('RUNTIME_BROKEN');
  await page.route('**/api/models/local-runtime/components/dlss5nr/install', (route) => route.fulfill({ status: 202, json: {
    id: 'updating-dlss', component_id: 'dlss5nr', version: '0.1.1', operation: 'install',
    state: 'running', stage: 'checking_component', revision: 1, cancel_requested: false, created_at: new Date().toISOString(),
  } }));
  await component.getByRole('button', { name: 'Update', exact: true }).click();
  await expect(component.getByRole('button', { name: 'Cancel task', exact: true })).toBeVisible();
  await expect(core.getByRole('button', { name: 'Cancel task', exact: true })).toHaveCount(0);
});

test('closing a pending log refresh keeps it closed without refreshing other data', async ({ page, request }) => {
  await request.post('/__test__/runtimes', { data: {} });
  await request.post('/api/models/local-runtime/cache/cleanup', { data: { mode: 'prune' } });
  await expect.poll(async () => (await (await request.get('/api/models/local-runtime/jobs')).json())[0].state).toBe('completed');
  let delayed = false, pending = false, release = () => {}, metadataReads = 0;
  page.on('request', (request) => {
    if (request.url().endsWith('/api/models/local-runtime/catalog') || request.url().endsWith('/api/models/local-runtime/storage')) metadataReads++;
  });
  await page.route('**/api/models/local-runtime/jobs/*/log', async (route) => {
    if (delayed) { pending = true; await new Promise<void>((resolve) => { release = resolve; }); }
    await route.fulfill({ json: { text: 'Cache maintenance completed.' } });
  });
  await runtimeView(page, 'en');
  await expect(page.getByRole('button', { name: 'Refresh status', exact: true })).toBeEnabled();
  const initialReads = metadataReads;
  await page.locator('.runtime-task-history > [data-slot="collapsible-trigger"]').click();
  await page.locator('.runtime-history').getByRole('button', { name: 'Task log', exact: true }).first().click();
  await expect(page.getByRole('dialog')).toContainText('Cache maintenance completed.');
  delayed = true;
  await page.getByRole('dialog').getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect.poll(() => pending).toBe(true);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  release();
  await expect(page.getByRole('button', { name: 'Refresh status', exact: true })).toBeEnabled();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(metadataReads).toBe(initialReads);
});
