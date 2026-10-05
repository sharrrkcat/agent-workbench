import { readFileSync } from 'node:fs';
import { test, expect, type APIRequestContext, type APIResponse, type Page } from '@playwright/test';
import { chooseOption } from './controls';

const words = (locale: string, namespace = 'personas') => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'));
async function json(response: Promise<APIResponse>) { const value = await response; expect(value.ok(), await value.text()).toBe(true); return value.json(); }
async function setup(request: APIRequestContext, count = 31) {
  const project = await json(request.post('/api/projects', { data: { kind: 'qqbot', name: 'Resource gallery',
    bot_account: String(Date.now()), websocket_url: 'ws://127.0.0.1:3001', keywords: ['bot'], context_policy: {} } }));
  const session = await json(request.post(`/api/projects/${project.id}/sessions`, { data: { title: 'Gallery conversation', target_kind: 'group', target_id: '7788' } }));
  const fixture = await json(request.post(`/__test__/qq/${session.session_id}/resources?count=${count}`));
  return { project, session, resources: fixture.resources as Array<{ asset_id: number; message_id: number }> };
}
async function cleanup(request: APIRequestContext, fixture: Awaited<ReturnType<typeof setup>>) {
  for (const resource of fixture.resources) await request.delete(`/api/qq/resources/${resource.asset_id}`);
  await request.delete(`/api/projects/${fixture.project.id}`);
}
async function entry(page: Page, projectId: string, title: string, width = 1366) {
  await page.goto(`/projects/${projectId}`);
  if (width === 390) await page.locator('[data-slot="sidebar-trigger"]').click();
  await page.locator(`[data-project-id="${projectId}"]`).getByRole('button', { name: title, exact: true }).click();
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
}

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 1280, 390]) {
  test.describe(`QQ resources ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: width === 390 ? 844 : 900 }, hasTouch: width === 390 });
    test('gallery layout, independent favorites, description drafts, animation and deletion', async ({ page, request }, info) => {
      const labels = words(locale), text = labels.qq.resources, common = words(locale, 'common');
      const fixture = await setup(request);
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      try {
        await entry(page, fixture.project.id, text.title, width);
        const cards = page.locator('[data-resource-id]');
        await expect(cards).toHaveCount(30);
        const tabsBox = (await page.getByRole('tablist', { name: text.filter }).boundingBox())!;
        const countBox = (await page.getByRole('status').filter({ hasText: /31/ }).boundingBox())!;
        expect(countBox.x).toBeGreaterThan(tabsBox.x + tabsBox.width);
        expect(Math.abs(countBox.y + countBox.height / 2 - tabsBox.y - tabsBox.height / 2)).toBeLessThan(2);
        expect(await page.locator('.qq-resource-grid').evaluate((node) => getComputedStyle(node).gridTemplateColumns.split(' ').length))
          .toBe(width === 1366 ? 6 : width === 1280 ? 5 : 2);
        const first = cards.first(), actions = first.locator('[data-slot="attachment-actions"]');
        if (width !== 390) {
          await page.mouse.move(1, 1);
          await expect(actions).toHaveCSS('opacity', '0');
          await first.locator('[data-slot="attachment-trigger"]').focus();
          await expect(actions).toHaveCSS('opacity', '1');
          await first.hover();
        } else await expect(actions).toHaveCSS('opacity', '1');
        await first.getByRole('button', { name: text.favorite, exact: true }).click();
        await expect(first.getByRole('button', { name: text.unfavorite, exact: true })).toHaveAttribute('aria-pressed', 'true');
        await expect(page.getByRole('dialog', { name: text.details })).toHaveCount(0);
        await page.screenshot({ path: info.outputPath('gallery.png') });
        await page.getByRole('tab', { name: text.favorites, exact: true }).click();
        await expect(cards).toHaveCount(1);
        await cards.first().locator('[data-slot="attachment-trigger"]').click();
        const sheet = page.getByRole('dialog', { name: text.details, exact: true });
        const input = sheet.getByRole('textbox', { name: text.description, exact: true });
        await expect(input).toBeFocused();
        await input.fill('A manually edited expression\n保留两行描述');
        await sheet.getByRole('button', { name: text.unfavorite, exact: true }).click();
        await expect(input).toHaveValue('A manually edited expression\n保留两行描述');
        await sheet.getByRole('button', { name: labels.save, exact: true }).click();
        await expect(sheet.getByText(text.saved, { exact: true })).toBeVisible();
        await expect(sheet).toBeVisible();
        const box = (await sheet.boundingBox())!;
        expect(box.width).toBeCloseTo(width === 390 ? 390 : 480, 0);
        await page.screenshot({ path: info.outputPath('sheet.png') });
        await page.keyboard.press('Escape');
        await expect(sheet).toBeHidden();
        await expect(cards).toHaveCount(0);
        await page.getByRole('tab', { name: text.all, exact: true }).click();
        await expect(cards).toHaveCount(30);
        await chooseOption(page.getByRole('combobox', { name: text.sort }), text.sortOptions.size_asc);
        await expect(page).toHaveURL(/sort=size&order=asc/);
        await expect(cards).toHaveCount(30);
        await chooseOption(page.getByRole('combobox', { name: text.sort }), text.sortOptions.created_at_desc);
        await expect(cards).toHaveCount(30);
        await page.getByRole('link', { name: common.pagination.next, exact: true }).click();
        await expect(cards).toHaveCount(1);
        await expect(page).toHaveURL(/page=2/);
        await page.reload();
        await expect(cards).toHaveCount(1);
        await cards.first().locator('[data-slot="attachment-trigger"]').click();
        await expect(sheet.locator('img')).toHaveAttribute('src', /\.gif$/);
        await input.fill('Unsaved description');
        await page.keyboard.press('Escape');
        const confirmation = page.getByRole('alertdialog');
        await expect(confirmation).toBeVisible();
        await confirmation.getByRole('button', { name: common.cancel, exact: true }).click();
        await expect(input).toHaveValue('Unsaved description');
        await sheet.getByRole('button', { name: text.reset, exact: true }).click();
        await expect(input).toHaveValue('Gallery image 1');
        await page.keyboard.press('Escape');
        await expect(sheet).toBeHidden();
        await expect(cards.first().locator('[data-slot="attachment-trigger"]')).toBeFocused();
        if (width !== 390) await cards.first().hover();
        await cards.first().getByRole('button', { name: text.delete, exact: true }).click();
        await confirmation.getByRole('button', { name: common.cancel, exact: true }).click();
        await expect(cards).toHaveCount(1);
        await cards.first().getByRole('button', { name: text.delete, exact: true }).click();
        await confirmation.getByRole('button', { name: common.confirm, exact: true }).click();
        await expect(page).toHaveURL(/page=1/);
        await expect(cards).toHaveCount(30);
        await expect(page.getByRole('link', { name: common.pagination.next, exact: true })).toHaveAttribute('aria-disabled', 'true');
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        await page.goto(`/projects/${fixture.project.id}?session=${fixture.session.session_id}`);
        const deleted = page.locator(`[data-qq-incoming="${fixture.resources[0].message_id}"]`);
        await expect(deleted.locator('[data-qq-media-state="deleted"]')).toHaveText(text.imagePlaceholder);
        await expect(deleted.locator('img')).toHaveCount(0);
        expect(errors).toEqual([]);
      } finally { await cleanup(request, fixture); }
    });
  });
}

test('failures retain drafts and records; stale reads and browser history respect selection', async ({ page, request }) => {
  const labels = words('en'), text = labels.qq.resources, common = words('en', 'common');
  const fixture = await setup(request, 3);
  await page.addInitScript(() => localStorage.setItem('cogita.locale', 'en'));
  try {
    await entry(page, fixture.project.id, text.title);
    const cards = page.locator('[data-resource-id]');
    await expect(cards).toHaveCount(3);
    let release!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    let started!: () => void;
    const reading = new Promise<void>((resolve) => { started = resolve; });
    await page.route('**/api/qq/resources?*', async (route) => {
      if (new URL(route.request().url()).searchParams.get('sort') !== 'size') { await route.continue(); return; }
      const response = await route.fetch();
      started(); await held;
      await route.fulfill({ response });
    });
    await chooseOption(page.getByRole('combobox', { name: text.sort }), text.sortOptions.size_asc);
    await reading;
    await page.getByRole('tab', { name: text.favorites, exact: true }).click();
    // Let the current empty read pass, then deliver the old all-images response.
    release();
    await expect(cards).toHaveCount(0);
    await expect(page.getByText(text.empty, { exact: true })).toBeVisible();
    await page.unroute('**/api/qq/resources?*');
    await page.getByRole('tab', { name: text.all, exact: true }).click();
    await expect(cards).toHaveCount(3);
    await cards.first().locator('[data-slot="attachment-trigger"]').click();
    const sheet = page.getByRole('dialog', { name: text.details, exact: true });
    const input = sheet.getByRole('textbox', { name: text.description, exact: true });
    await input.fill('Retain this draft after failure');
    await page.route('**/api/qq/resources/*', (route) => route.fulfill({ status: 503,
      json: { error: { code: 'FIXTURE_FAILURE', message: 'Try again later.' } } }));
    await sheet.getByRole('button', { name: labels.save, exact: true }).click();
    await expect(sheet.getByRole('alert')).toContainText('FIXTURE_FAILURE');
    await expect(input).toHaveValue('Retain this draft after failure');
    await expect(sheet.getByRole('button', { name: labels.save, exact: true })).toBeEnabled();
    await sheet.getByRole('button', { name: text.delete, exact: true }).click();
    await page.getByRole('alertdialog').getByRole('button', { name: common.confirm, exact: true }).click();
    await expect(sheet.getByRole('alert')).toContainText('FIXTURE_FAILURE');
    expect((await json(request.get('/api/qq/resources'))).total).toBe(3);
    await page.unroute('**/api/qq/resources/*');
    await page.evaluate(() => history.back());
    const confirmation = page.getByRole('alertdialog');
    await expect(confirmation).toBeVisible();
    await confirmation.getByRole('button', { name: common.cancel, exact: true }).click();
    await expect(input).toHaveValue('Retain this draft after failure');
    await sheet.getByRole('button', { name: labels.save, exact: true }).click();
    await expect(sheet.getByText(text.saved, { exact: true })).toBeVisible();
    await input.fill('Discard this draft when accepting browser history');
    await page.evaluate(() => history.back());
    await expect(confirmation).toBeVisible();
    await confirmation.getByRole('button', { name: common.confirm, exact: true }).click();
    await expect(sheet).toBeHidden();
    await expect(page).toHaveURL(/favorite=favorites/);
    await expect(cards).toHaveCount(0);
  } finally { await cleanup(request, fixture); }
});

test('orphan favorites are shared across Projects and removal confirms their deletion', async ({ page, request }) => {
  const labels = words('en'), text = labels.qq.resources, common = words('en', 'common');
  const fixture = await setup(request, 1);
  const other = await json(request.post('/api/projects', { data: { kind: 'qqbot', name: 'Other QQBot', bot_account: String(Date.now()), websocket_url: 'ws://127.0.0.1:3002', context_policy: {} } }));
  await page.addInitScript(() => localStorage.setItem('cogita.locale', 'en'));
  try {
    await json(request.patch(`/api/qq/resources/${fixture.resources[0].asset_id}`, { data: { is_favorite: true } }));
    await json(request.delete(`/api/projects/${fixture.project.id}`));
    await page.goto(`/projects/${other.id}/resources`);
    const card = page.locator('[data-resource-id]');
    await expect(card).toHaveCount(1);
    await card.hover();
    await card.getByRole('button', { name: text.unfavorite, exact: true }).click();
    const confirmation = page.getByRole('alertdialog');
    await expect(confirmation).toContainText(text.orphanConfirm);
    await confirmation.getByRole('button', { name: common.cancel, exact: true }).click();
    await expect(card.getByRole('button', { name: text.unfavorite, exact: true })).toHaveAttribute('aria-pressed', 'true');
    await card.getByRole('button', { name: text.unfavorite, exact: true }).click();
    await confirmation.getByRole('button', { name: common.confirm, exact: true }).click();
    await expect(card).toHaveCount(0);
  } finally { await cleanup(request, fixture); await request.delete(`/api/projects/${other.id}`); }
});
