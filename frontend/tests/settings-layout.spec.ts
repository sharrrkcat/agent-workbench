import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';
import { answerConfirmation, backToChat, chooseOption, navigateSettings, openSidebar } from './controls';

const words = (locale: string, namespace: string) =>
  JSON.parse(
    readFileSync(new URL(`../src/i18n/resources/${locale}/${namespace}.json`, import.meta.url), 'utf8'),
  );

async function noPageOverflow(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(() => ({
        x: document.documentElement.scrollWidth - innerWidth,
        y: document.documentElement.scrollHeight - innerHeight,
      })),
    )
    .toEqual({ x: 0, y: 0 });
}

for (const locale of ['en', 'zh-CN']) {
  const settings = words(locale, 'settings'),
    llm = words(locale, 'llm');
  const knowledge = words(locale, 'knowledge');
  const personas = words(locale, 'personas');
  for (const viewport of [
    { width: 1366, height: 900 },
    { width: 390, height: 844 },
  ]) {
    test.describe(`Settings layout ${locale} ${viewport.width}`, () => {
      test.use({ viewport, hasTouch: viewport.width === 390 });
      test.beforeEach(async ({ page }) => {
        await page.addInitScript((value) => localStorage.setItem('cogita.locale', value), locale);
      });

      test('all grouped pages have bounded content and stable navigation', async ({ page }, info) => {
        const errors: string[] = [];
        page.on('pageerror', (error) => errors.push(error.message));
        await page.goto('/');
        await expect(page.locator('.composer textarea')).toBeVisible();
        await expect(page.locator('.topbar')).toBeVisible();
        const homeHeader = (await page.locator('.topbar').boundingBox())!;
        const homeToggle = await page.locator('[data-sidebar="trigger"]').boundingBox();
        await openSidebar(page);
        await expect.poll(async () => (await page.locator('.session-sidebar').boundingBox())!.x).toBe(0);
        const homeBrand = await page.locator('.session-sidebar .sidebar-brand').boundingBox();
        await page.goto('/settings?tab=general');
        await expect(page.locator('.settings-header')).toBeVisible();
        expect(await page.locator('[data-sidebar="trigger"]').boundingBox()).toEqual(homeToggle);
        if (viewport.width >= 768)
          expect((await page.locator('.settings-header').boundingBox())!.height).toBe(homeHeader.height);
        await expect(page.locator('.settings-header .text-muted-foreground')).toHaveCount(0);
        await openSidebar(page);
        const sidebar = page.locator('.settings-sidebar');
        await expect.poll(async () => (await sidebar.boundingBox())!.x).toBe(0);
        await expect(sidebar.locator('.sidebar-brand')).toHaveText(settings.title);
        await expect(sidebar.locator('[data-slot="sidebar-header"]')).toHaveText(settings.title);
        expect(await sidebar.locator('.sidebar-brand').boundingBox()).toEqual(homeBrand);
        const historyLength = await page.evaluate(() => history.length);
        for (const section of ['models', 'knowledge', 'worldbook']) {
          const menu = sidebar.getByRole('list', { name: settings[section], exact: true });
          const toggle = menu.getByRole('button', { name: settings[section], exact: true });
          await expect(toggle).toHaveAttribute('aria-expanded', 'false');
          await expect(menu.getByRole('button')).toHaveCount(1);
          await toggle.click();
          await expect(toggle).toHaveAttribute('aria-expanded', 'true');
          await toggle.press('Enter');
          await expect(toggle).toHaveAttribute('aria-expanded', 'false');
        }
        await expect(page).toHaveURL('/settings?tab=general');
        expect(await page.evaluate(() => history.length)).toBe(historyLength);
        await page.screenshot({ path: info.outputPath('collapsed-sidebar.png'), animations: 'disabled' });
        const pages = [
          ['general', ''],
          ['models', 'profiles'],
          ['models', 'providers'],
          ['models', 'localRuntime'],
          ['models', 'service'],
          ['personas', 'user'],
          ['personas', 'agent'],
          ['personas', 'roleplay_user'],
          ['personas', 'character'],
          ['knowledge', 'list'],
          ['knowledge', 'settings'],
          ['worldbook', 'list'],
          ['worldbook', 'settings'],
          ['tools', ''],
        ];
        for (const [section, view] of pages) {
          const label = !view
            ? settings[section]
            : section === 'models'
              ? llm[view]
              : section === 'personas' ? personas.collections[view] : settings.resources[view];
          await navigateSettings(page, settings[section], label, section === 'personas' ? settings.sidebarGroups[['user', 'agent'].includes(view) ? 'daily' : 'roleplay'] : undefined);
          await expect(page).toHaveURL(`/settings?tab=${section}${view ? `&view=${view}` : ''}`);
          await expect(page.locator('.settings-heading h1')).toContainText(settings[section]);
          await noPageOverflow(page);
          if (viewport.width === 390)
            await expect(page.locator('[data-sidebar="trigger"]')).toHaveAttribute('aria-expanded', 'false');
          if (section === 'models') {
            await expect(page.locator('.settings-content [role="tablist"]')).toHaveCount(0);
            if (view === 'profiles')
              await expect(page.getByLabel(llm.defaultModel, { exact: true })).toBeVisible();
            else await expect(page.getByLabel(llm.defaultModel, { exact: true })).toBeHidden();
          }
          if (section === 'tools')
            expect(
              await page
                .locator('.tool-selector')
                .evaluateAll((buttons) =>
                  buttons
                    .filter((button) => button.scrollWidth > button.clientWidth + 1)
                    .map((button) => button.textContent),
                ),
            ).toEqual([]);
          await page.screenshot({
            path: info.outputPath(`${section}-${view || 'page'}.png`),
            animations: 'disabled',
          });
        }
        await openSidebar(page);
        await expect(sidebar.locator('nav > [data-slot="sidebar-group"]')).toHaveCount(4);
        await expect(sidebar.locator('[data-slot="sidebar-group-label"]')).toHaveText([
          settings.sidebarGroups.application,
          settings.sidebarGroups.execution,
          settings.sidebarGroups.daily,
          settings.sidebarGroups.roleplay,
        ]);
        await expect(sidebar.locator('.settings-domain-menu')).toHaveCount(7);
        await expect(sidebar.locator('button[data-settings-page]')).toHaveCount(14);
        for (const [section, count] of [
          ['models', 4],
          ['knowledge', 2],
          ['worldbook', 2],
        ] as const) {
          const menu = sidebar.getByRole('list', { name: settings[section], exact: true });
          const toggle = menu.locator(`button[data-settings-menu="${section}"]`);
          await expect(toggle).toHaveText(settings[section]);
          if ((await toggle.getAttribute('aria-expanded')) === 'false') await toggle.click();
          await expect(
            menu.locator(
              '[data-slot="collapsible-content"] > [data-slot="sidebar-menu"] > [data-slot="sidebar-menu-item"]',
            ),
          ).toHaveCount(count);
        }
        await expect(sidebar.locator('[aria-current="page"]')).toHaveText(settings.tools);
        expect((await sidebar.boundingBox())!.width).toBeCloseTo(viewport.width === 390 ? 288 : 256, 1);
        await sidebar.locator('[data-slot="sidebar-content"]').evaluate((node) => {
          node.scrollTop = 0;
        });
        await page.screenshot({ path: info.outputPath('settings-sidebar.png'), animations: 'disabled' });
        if (viewport.width === 390) {
          await expect(page.getByRole('dialog', { name: settings.title, exact: true })).toBeVisible();
          expect(
            await sidebar.locator('button').evaluateAll((buttons) =>
              buttons
                .filter((button) => {
                  const r = button.getBoundingClientRect();
                  return r.width > 0 && (r.width < 44 || r.height < 44);
                })
                .map((button) => button.textContent),
            ),
          ).toEqual([]);
          await page.keyboard.press('Escape');
          await expect(page.locator('[data-sidebar="trigger"]')).toBeFocused();
        }
        await backToChat(page);
        await expect(page).toHaveURL('/');
        await noPageOverflow(page);
        expect(errors).toEqual([]);
      });

      test('HTTP and normalized request limits validate, autosave and persist', async ({ page, request }, info) => {
        const path = '/api/models/settings';
        const original = await (await request.get(path)).json();
        expect((await request.patch(path, { data: {
          max_request_mb: 32, max_normalized_request_mb: 128, external_enabled: false,
        } })).ok()).toBeTruthy();
        try {
          await page.goto('/settings?tab=models&view=service');
          const http = page.getByRole('spinbutton', { name: llm.bodyLimit, exact: true });
          const normalized = page.getByRole('spinbutton', { name: llm.normalizedBodyLimit, exact: true });
          await expect(http).toHaveValue('32');
          await expect(normalized).toHaveValue('128');
          await expect(normalized).toBeEnabled();
          await expect(page.getByRole('switch', { name: llm.externalEnabled, exact: true })).not.toBeChecked();
          await expect(page.getByText(llm.normalizedBodyLimitHelp, { exact: true })).toBeVisible();
          const writes: Record<string, number>[] = [];
          page.on('request', (sent) => {
            if (sent.url().endsWith(path) && sent.method() === 'PATCH') writes.push(sent.postDataJSON());
          });
          const fields = [
            { input: http, field: 'max_request_mb', max: 100 },
            { input: normalized, field: 'max_normalized_request_mb', max: 1024 },
          ];
          for (const { input, max } of fields) {
            for (const value of ['', '0', '1.5', String(max + 1)]) {
              await input.fill(value);
              await input.press('Tab');
              await expect(input).toHaveAttribute('aria-invalid', 'true');
              expect(await input.evaluate((node: HTMLInputElement) => node.validity.valid)).toBe(false);
            }
          }
          expect(writes).toEqual([]);
          for (const { input, field, max } of fields) {
            for (const value of [1, max]) {
              const saved = page.waitForResponse((response) =>
                response.url().endsWith(path) && response.request().method() === 'PATCH',
              );
              await input.fill(String(value));
              await input.press(field === 'max_request_mb' ? 'Tab' : 'Enter');
              expect((await saved).ok()).toBeTruthy();
              await expect(input).toBeEnabled();
              await expect(input).toHaveAttribute('aria-invalid', 'false');
              expect(writes.at(-1)).toEqual({ [field]: value });
              expect((await (await request.get(path)).json())[field]).toBe(value);
            }
          }
          expect(writes).toHaveLength(4);
          await page.reload();
          await expect(http).toHaveValue('100');
          await expect(normalized).toHaveValue('1024');
          await noPageOverflow(page);
          await page.screenshot({ path: info.outputPath('request-limits.png'), animations: 'disabled' });
        } finally {
          expect((await request.patch(path, { data: {
            max_request_mb: original.max_request_mb,
            max_normalized_request_mb: original.max_normalized_request_mb,
            external_enabled: original.external_enabled,
          } })).ok()).toBeTruthy();
        }
      });

      test('global drafts survive subpages and guarded routes keep selection and drawer state', async ({
        page,
      }) => {
        await page.goto('/settings?tab=knowledge&view=settings');
        const chunk = page.getByLabel(knowledge.chunkSize, { exact: true });
        const original = Number(await chunk.inputValue());
        await chunk.fill(String(original + 1));
        await navigateSettings(page, settings.knowledge, settings.resources.list);
        await expect(chunk).toBeHidden();
        await navigateSettings(page, settings.knowledge, settings.resources.settings);
        await expect(chunk).toHaveValue(String(original + 1));
        await navigateSettings(page, settings.general);
        await answerConfirmation(page, false, locale);
        await expect(page).toHaveURL('/settings?tab=knowledge&view=settings');
        await expect(page.locator('.settings-sidebar [aria-current="page"]')).toHaveText(
          settings.resources.settings,
        );
        if (viewport.width === 390) {
          await expect(page.locator('[data-sidebar="trigger"]')).toHaveAttribute('aria-expanded', 'true');
          await page.keyboard.press('Escape');
        }
        await expect(chunk).toHaveValue(String(original + 1));
        await navigateSettings(page, settings.general);
        await answerConfirmation(page, true, locale);
        await expect(page).toHaveURL('/settings?tab=general');
        await page.goBack();
        await expect(page).toHaveURL('/settings?tab=knowledge&view=settings');
        await expect(chunk).toHaveValue(String(original));
        await page.goForward();
        await expect(page).toHaveURL('/settings?tab=general');
      });

      test('resource details keep local tabs and confirm return from their Resources entry', async ({ page }) => {
        await page.goto('/settings?tab=knowledge&view=list');
        await page.getByRole('button', { name: knowledge.addBase, exact: true }).click();
        await page.getByLabel(knowledge.baseName, { exact: true }).fill('Unsaved navigation draft');
        await expect(page.getByRole('tab', { name: knowledge.config, exact: true })).toBeVisible();
        const length = await page.evaluate(() => history.length);
        await navigateSettings(page, settings.knowledge, settings.resources.list);
        await answerConfirmation(page, false, locale);
        if (viewport.width === 390) await page.keyboard.press('Escape');
        await expect(page.getByLabel(knowledge.baseName, { exact: true })).toHaveValue(
          'Unsaved navigation draft',
        );
        await navigateSettings(page, settings.knowledge, settings.resources.settings);
        await answerConfirmation(page, true, locale);
        await expect(page).toHaveURL('/settings?tab=knowledge&view=settings');
        await page.goBack();
        await expect(page.getByRole('button', { name: knowledge.addBase, exact: true })).toBeVisible();
        expect(await page.evaluate(() => history.length)).toBe(length + 1);
      });
    });
  }
}

test('direct links refresh, invalid views default, history preserves model drafts and hides overlays', async ({
  page,
}) => {
  await page.addInitScript(() => localStorage.setItem('cogita.locale', 'en'));
  await page.goto('/settings?tab=models&view=providers');
  await page.getByRole('button', { name: 'Add provider', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Name', { exact: true }).fill('Retained provider draft');
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
  await navigateSettings(page, 'Models', 'Local Runtime');
  await page.reload();
  await expect(page).toHaveURL('/settings?tab=models&view=localRuntime');
  await expect(page.getByRole('group', { name: 'Local installation', exact: true }).getByRole('button', { name: 'Install local runtime', exact: true })).toBeVisible();
  await navigateSettings(page, 'Models', 'Providers');
  await page.getByRole('button', { name: 'Add provider', exact: true }).click();
  await dialog.getByLabel('Name', { exact: true }).fill('History provider draft');
  await page.goBack();
  await expect(page).toHaveURL('/settings?tab=models&view=localRuntime');
  await expect(dialog).toHaveCount(0);
  await page.goForward();
  await expect(dialog.getByLabel('Name', { exact: true })).toHaveValue('History provider draft');
  await page.goto('/settings?tab=models&view=unknown');
  await expect(page.getByLabel('Default chat model', { exact: true })).toBeVisible();
  const length = await page.evaluate(() => history.length);
  await navigateSettings(page, 'Models', 'Model profiles');
  await expect(page).toHaveURL('/settings?tab=models&view=unknown');
  expect(await page.evaluate(() => history.length)).toBe(length);
  await page.goto('/settings?tab=unknown&view=settings');
  await expect(page.locator('.settings-heading h1')).toHaveText('General');
});

test('home and settings retain the shared desktop sidebar visibility through history', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('cogita.locale', 'en'));
  await page.goto('/');
  await openSidebar(page);
  await page.locator('.session-sidebar').getByRole('button', { name: 'Settings', exact: true }).click();
  await expect(page).toHaveURL('/settings');
  const trigger = page.locator('[data-sidebar="trigger"]');
  await trigger.click();
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await page.goBack();
  await expect(page).toHaveURL('/');
  await expect(page.locator('.session-sidebar')).toHaveAttribute('inert', '');
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await page.goForward();
  await expect(page).toHaveURL('/settings');
  await expect(page.locator('.settings-sidebar')).toHaveAttribute('inert', '');
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await openSidebar(page);
  await noPageOverflow(page);
});

test('subpage history closes transient popups while retaining selected values', async ({ page, request }) => {
  const llm = words('en', 'llm');
  const knowledge = words('en', 'knowledge');
  await page.addInitScript(() => localStorage.setItem('cogita.locale', 'en'));
  await page.goto('/settings?tab=models&view=providers');
  await navigateSettings(page, 'Models', llm.profiles);
  const kind = page.locator('.model-toolbar').getByLabel(llm.kind, { exact: true });
  await chooseOption(kind, llm.kinds.embedding);
  await kind.click();
  await expect(page.getByRole('listbox')).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL('/settings?tab=models&view=providers');
  await expect(page.getByRole('listbox')).toHaveCount(0);
  await page.goForward();
  await expect(kind).toContainText(llm.kinds.embedding);
  const auxiliary = page.getByLabel(llm.utilityModel, { exact: true });
  const selection = await auxiliary.textContent();
  await auxiliary.click();
  await expect(page.getByRole('listbox')).toBeVisible();
  await page.goBack();
  await expect(page.getByRole('listbox')).toHaveCount(0);
  await page.goForward();
  await expect(auxiliary).toHaveText(selection!);

  const jobs = await (await request.get('/api/models/local-runtime/jobs')).json();
  await navigateSettings(page, 'Models', llm.localRuntime);
  await page
    .locator('.runtime-cache-actions')
    .getByRole('button', { name: 'Clear cache', exact: true })
    .click();
  await expect(page.getByRole('alertdialog')).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL('/settings?tab=models&view=profiles');
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  expect(await (await request.get('/api/models/local-runtime/jobs')).json()).toEqual(jobs);

  await navigateSettings(page, 'Knowledge', 'Resources');
  await navigateSettings(page, 'Knowledge', 'Global settings');
  const reranker = page.getByLabel(knowledge.rerankerProfile, { exact: true });
  const rerankerSelection = await reranker.textContent();
  await reranker.click();
  await expect(page.getByRole('listbox')).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL('/settings?tab=knowledge&view=list');
  await expect(page.getByRole('listbox')).toHaveCount(0);
  await page.goForward();
  await expect(reranker).toHaveText(rerankerSelection!);
});

for (const viewport of [
  { width: 767, height: 600 },
  { width: 768, height: 600 },
  { width: 390, height: 500 },
]) {
  test(`settings scroll regions and responsive boundary ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto('/settings?tab=knowledge&view=settings');
    await openSidebar(page);
    const sidebar = page.locator('.settings-sidebar');
    for (const toggle of await sidebar.locator('[data-settings-menu]').all()) await toggle.click();
    const header = sidebar.locator('[data-slot="sidebar-header"]');
    const footer = sidebar.locator('[data-slot="sidebar-footer"]');
    const before = { header: (await header.boundingBox())!.y, footer: (await footer.boundingBox())!.y };
    await sidebar.locator('[data-slot="sidebar-content"]').evaluate((node) => {
      node.scrollTop = node.scrollHeight;
    });
    expect(await sidebar.locator('[data-slot="sidebar-content"]').evaluate((node) => node.scrollTop)).toBeGreaterThan(0);
    expect((await header.boundingBox())!.y).toBe(before.header);
    expect((await footer.boundingBox())!.y).toBe(before.footer);
    if (viewport.width < 768) await page.keyboard.press('Escape');
    const pageHeader = page.locator('.settings-header');
    const y = (await pageHeader.boundingBox())!.y;
    await page.locator('.settings-scroll').evaluate((node) => {
      node.scrollTop = node.scrollHeight;
    });
    expect((await pageHeader.boundingBox())!.y).toBe(y);
    await noPageOverflow(page);
  });
}
