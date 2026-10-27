import { readFileSync } from 'node:fs';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { saveHistory, type MatchRecord } from '../src/components/playground/farkle/history';
import { openSidebar } from './controls';

const translations = (locale: string) => JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/common.json`, import.meta.url), 'utf8'));
test('standalone favicon and English browser startup ignore application storage', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'languages', { value: ['en-US'] });
    localStorage.setItem('cogita.locale', 'zh-CN');
    localStorage.setItem('cogita.farkle.inventory', 'unrelated');
  });
  await page.goto('/');
  await expect(page).toHaveTitle('Farkle');
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.locator('.sidebar-brand')).toHaveText('Farkle');
  await expect(page.locator('.farkle-sidebar').getByRole('button', { name: 'New Game', exact: true })).toBeVisible();
  await expect(page.locator('[data-merchant-balance]')).toHaveText('0');
  await expect(page.locator('.farkle-sidebar [data-slot="sidebar-footer"]')).toHaveCount(0);
  await expect(page.locator('.farkle-table canvas')).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('farkle.locale'))).toBe('en');
  expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'))).toBe('unrelated');
  const icon = page.locator('link[rel="icon"]');
  await expect(icon).toHaveAttribute('type', 'image/png');
  await expect(icon).toHaveAttribute('sizes', '64x64');
  const iconUrl = new URL((await icon.getAttribute('href'))!, page.url());
  expect(iconUrl.origin).toBe(new URL(page.url()).origin);
  const response = await page.request.get(iconUrl.href);
  expect(response.ok()).toBe(true);
  expect(response.headers()['content-type']).toContain('image/png');
  const dimensions = await page.evaluate(async (url) => {
    const image = new Image(); image.src = url; await image.decode();
    return [image.naturalWidth, image.naturalHeight];
  }, iconUrl.href);
  expect(dimensions).toEqual([64, 64]);
});

for (const scenario of [
  { name: 'Simplified Chinese', languages: ['zh-CN'], expected: 'zh-CN' },
  { name: 'Traditional Chinese', languages: ['zh-TW'], expected: 'zh-CN' },
  { name: 'Hong Kong Chinese', languages: ['zh-HK'], expected: 'zh-CN' },
  { name: 'English variant', languages: ['en-GB'], expected: 'en' },
  { name: 'unsupported languages', languages: ['fr-FR', 'ja-JP'], expected: 'en' },
  { name: 'first supported Chinese', languages: ['fr-FR', 'zh-Hans', 'en-US'], expected: 'zh-CN' },
  { name: 'first supported English', languages: ['ja-JP', 'en-US', 'zh-CN'], expected: 'en' },
  { name: 'empty language list', languages: [], language: 'zh-CN', expected: 'zh-CN' },
  { name: 'unavailable language list', language: 'zh-TW', expected: 'zh-CN' },
  { name: 'saved English', languages: ['zh-CN'], stored: 'en', expected: 'en' },
  { name: 'saved Chinese', languages: ['en-US'], stored: 'zh-CN', expected: 'zh-CN' },
  { name: 'invalid saved preference', languages: ['zh-CN'], stored: 'fr', expected: 'zh-CN' },
]) test(`initial language: ${scenario.name}, then retain it after browser language changes`, async ({ page }) => {
  await page.addInitScript((scenario) => {
    Object.defineProperty(navigator, 'languages', { get: () => sessionStorage.getItem('changed-language')
      ? [scenario.expected === 'en' ? 'zh-CN' : 'en-US'] : scenario.languages });
    Object.defineProperty(navigator, 'language', { value: scenario.language ?? 'en-US' });
    if (!sessionStorage.getItem('seeded')) {
      if (scenario.stored) localStorage.setItem('farkle.locale', scenario.stored);
      sessionStorage.setItem('seeded', 'true');
    }
  }, scenario);
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('lang', scenario.expected);
  await expect(page.locator('.farkle-sidebar').getByRole('button', {
    name: translations(scenario.expected).farkle.newGame, exact: true,
  })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('farkle.locale'))).toBe(scenario.expected);
  await page.evaluate(() => sessionStorage.setItem('changed-language', 'true'));
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('lang', scenario.expected);
});

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  const common = translations(locale), words = common.farkle, touch = width === 390;
  test.describe(`Standalone ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: touch ? 844 : 900 }, hasTouch: touch });
    const press = (locator: Locator) => touch ? locator.tap() : locator.click();
    const table = (page: Page) => page.locator('.farkle-table');
    const dialog = (page: Page) => page.getByRole('dialog');
    async function menu(page: Page, name: string) {
      await openSidebar(page);
      await press(page.locator('.farkle-sidebar').getByRole('button', { name, exact: true }));
    }
    async function start(page: Page) {
      await menu(page, words.newGame);
      await press(dialog(page).getByRole('button', { name: words.chooseDice, exact: true }));
      await press(dialog(page).getByRole('button', { name: words.startGame, exact: true }));
      await expect(table(page)).toHaveAttribute('data-busy', 'false');
      await expect(page.locator('[data-die-id]')).toHaveCount(6);
    }
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((locale) => {
        if (!localStorage.getItem('farkle.locale')) localStorage.setItem('farkle.locale', locale);
        Math.random = () => 0;
      }, locale);
    });

    test('static resources, sidebar, retained matches, AI and settlement', async ({ page }, info) => {
      const errors: string[] = [], requests: string[] = [], workers: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      page.on('request', (request) => requests.push(request.url()));
      page.on('requestfailed', (request) => errors.push(`Request failed: ${request.url()}`));
      page.on('response', (response) => { if (response.status() >= 400) errors.push(`HTTP ${response.status()}: ${response.url()}`); });
      page.on('websocket', (socket) => errors.push(`Unexpected WebSocket: ${socket.url()}`));
      page.on('worker', (worker) => workers.push(worker.url()));
      await page.goto('/');
      await expect(page).toHaveTitle('Farkle');
      await openSidebar(page);
      await expect(page.locator('.sidebar-brand')).toHaveText('Farkle');
      await expect(page.locator('.farkle-sidebar [data-slot="sidebar-footer"]')).toHaveCount(0);
      if (touch) await page.keyboard.press('Escape');
      await expect(table(page).locator('canvas')).toBeVisible();
      await start(page);
      await press(page.locator('[data-die-id="B0"]'));
      await expect(page.locator('[data-die-id="B0"]')).toHaveAttribute('data-state', 'selected');
      await page.screenshot({ path: info.outputPath('table.png') });

      await menu(page, words.history);
      await expect(page).toHaveURL(/\/\?view=history&page=1$/);
      await expect(page.getByText(words.historyEmpty, { exact: true })).toBeVisible();
      await page.goBack();
      await expect(page.locator('[data-die-id="B0"]')).toHaveAttribute('data-state', 'selected');
      await page.goForward();
      await press(page.locator('.topbar').getByRole('button', { name: words.backToTable, exact: true }));
      await expect(page.locator('[data-die-id="B0"]')).toHaveAttribute('data-state', 'selected');
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await expect(table(page)).toHaveAttribute('data-player', 'A');
      await expect(dialog(page)).toBeVisible({ timeout: 20000 });
      await expect(table(page)).toHaveAttribute('data-phase', 'finished');
      expect(workers.some((url) => /ai\.worker.*\.js/.test(url))).toBe(true);
      await press(dialog(page).getByRole('button', { name: common.close, exact: true }));
      await menu(page, words.exitGame);
      await openSidebar(page);
      await expect(page.locator('.farkle-sidebar [data-slot="sidebar-footer"]')).toHaveCount(0);
      if (touch) await page.keyboard.press('Escape');

      await start(page);
      for (let index = 0; index < 6; index++) await press(page.locator(`[data-die-id="B${index}"]`));
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await expect(dialog(page)).toBeVisible();
      await expect(page.locator('[data-rewards]')).toBeVisible();
      await press(dialog(page).getByRole('button', { name: common.close, exact: true }));
      await menu(page, words.history);
      await expect(page.locator('[data-history-record]')).toHaveCount(2);
      await page.screenshot({ path: info.outputPath('history.png') });
      await page.reload();
      await expect(page.locator('[data-history-record]')).toHaveCount(2);
      expect(await page.evaluate(() => Object.keys(localStorage).every((key) => key.startsWith('farkle.')))).toBe(true);
      expect(requests.some((url) => /\.woff2(?:$|\?)/.test(url))).toBe(true);
      expect(requests.every((url) => url.startsWith(new URL(page.url()).origin + '/'))).toBe(true);
      expect(requests.some((url) => /\/api\/|\/playground\//.test(url))).toBe(false);
      expect(errors).toEqual([]);
    });

    test('history deep links, locale and inventory persistence, custom match and scoped reset', async ({ page }, info) => {
      await page.goto('/');
      const record: MatchRecord = {
        startedAt: 1793100000000, durationSeconds: 30, playerDice: Array(6).fill('normal'), opponentDice: Array(6).fill('normal'),
        playerScore: 1500, opponentScore: 200, targetScore: 1500, winner: 'B', level: 'beggars', opponentMode: 'dynamic',
        playerTurns: 1, opponentTurns: 1, playerRolls: 1, opponentRolls: 1, rulesVersion: 1, aiVersion: 1,
      };
      let encoded = '';
      saveHistory({ setItem(_key, value) { encoded = value; } }, Array.from({ length: 25 }, (_, index) => ({ ...record, startedAt: record.startedAt - index * 1000 })));
      await page.evaluate((encoded) => {
        localStorage.setItem('farkle.history', encoded);
        localStorage.setItem('cogita.locale', 'unrelated');
        localStorage.setItem('unrelated', 'keep');
      }, encoded);
      await page.goto('/?view=history&page=2');
      await expect(page.locator('[data-history-record]')).toHaveCount(5);
      await page.reload();
      await expect(page.locator('[data-history-record]')).toHaveCount(5);
      await press(page.getByRole('link', { name: common.pagination.previous, exact: true }));
      await expect(page.locator('[data-history-record]')).toHaveCount(20);
      await menu(page, words.backToTable);
      await menu(page, words.settings);
      await press(dialog(page).getByRole('button', { name: words.fillDice, exact: true }));
      const changedLocale = locale === 'en' ? 'zh-CN' : 'en', next = translations(changedLocale);
      await press(dialog(page).getByRole('button', { name: changedLocale === 'en' ? 'English' : '简体中文', exact: true }));
      await expect(page.locator('html')).toHaveAttribute('lang', changedLocale);
      await press(dialog(page).getByRole('button', { name: next.close, exact: true }));
      await page.reload();
      await expect(page.locator('html')).toHaveAttribute('lang', changedLocale);
      await expect(page.locator('[data-merchant-balance]')).toHaveText('999');
      const inventory = await page.evaluate(() => localStorage.getItem('farkle.inventory'));
      await menu(page, next.farkle.customGame);
      await dialog(page).getByRole('textbox', { name: next.farkle.targetScore }).fill('2');
      await press(dialog(page).getByRole('button', { name: next.farkle.choosePlayerDice, exact: true }));
      await press(dialog(page).getByRole('button', { name: next.farkle.startGame, exact: true }));
      await expect(table(page)).toHaveAttribute('data-busy', 'false');
      await press(page.locator('[data-die-id="B0"]'));
      await press(page.getByRole('button', { name: next.farkle.pass, exact: true }));
      await expect(dialog(page)).toBeVisible();
      await expect(page.locator('[data-rewards]')).toHaveCount(0);
      expect(await page.evaluate(() => localStorage.getItem('farkle.inventory'))).toBe(inventory);
      await press(dialog(page).getByRole('button', { name: next.close, exact: true }));
      await menu(page, next.farkle.settings);
      await press(dialog(page).getByRole('button', { name: next.farkle.clearCache, exact: true }));
      expect(await page.evaluate(() => ({ ...localStorage }))).toEqual({ 'farkle.locale': changedLocale, 'cogita.locale': 'unrelated', unrelated: 'keep' });
      await openSidebar(page);
      await expect(page.locator('.farkle-sidebar [data-slot="sidebar-footer"]')).toHaveCount(0);
      await page.screenshot({ path: info.outputPath('homepage.png') });
    });
  });
}
