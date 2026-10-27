import { readFileSync } from 'node:fs';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { openSidebar } from './controls';
import { HISTORY_KEY, readHistory, saveHistory, type MatchRecord } from '../src/components/playground/farkle/history';

const startedAt = 1793100000123;
const overshootScore = 9007199254741050;
const example: MatchRecord = {
  startedAt, durationSeconds: 630, playerDice: ['weighted', 'normal', 'aranka', 'normal', 'lu', 'devil'],
  opponentDice: ['merchant', 'heavenly', 'ci', 'fer', 'odd', 'even'], playerScore: 5350, opponentScore: 3800,
  targetScore: 5000, winner: 'B', playerTurns: 11, opponentTurns: 10, playerRolls: 25, opponentRolls: 24,
  level: null, opponentMode: 'wild', rulesVersion: 1, aiVersion: 1,
};
const encode = (records: MatchRecord[]) => {
  let raw = ''; saveHistory({ setItem(_key, value) { raw = value; } }, records); return raw;
};
const saved = async (page: Page) => {
  const raw = await page.evaluate((key) => localStorage.getItem(key), HISTORY_KEY);
  return readHistory({ getItem() { return raw; } });
};

async function expectResponsiveRecord(page: Page) {
  const row = page.locator('[data-history-record]').first();
  const layout = await row.evaluate((node) => {
    const box = (selector: string, text = false) => {
      const element = node.querySelector(selector)!;
      const range = document.createRange(); range.selectNodeContents(element);
      const rect = text ? range.getBoundingClientRect() : element.getBoundingClientRect();
      return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom, center: (rect.top + rect.bottom) / 2 };
    };
    const row = node.getBoundingClientRect(), style = getComputedStyle(node);
    return { available: node.closest('.farkle-history')!.clientWidth, width: node.clientWidth, scrollWidth: node.scrollWidth,
      centerX: (row.left + row.right) / 2, contentRight: row.right - parseFloat(style.paddingRight) - parseFloat(style.borderRightWidth),
      columnGap: parseFloat(style.columnGap), time: box('.farkle-history-time'),
      start: box('.farkle-history-start', true), outcome: box('.farkle-history-outcome', true),
      duration: box('.farkle-history-duration', true),
      scores: box('.farkle-history-scores'), player: box('.farkle-history-player'), opponent: box('.farkle-history-opponent'),
      sideVisible: getComputedStyle(node.querySelector('.farkle-history-side')!).display !== 'none',
      dice: [...node.querySelectorAll('[data-history-die] img')].map((image) => {
        const rect = image.getBoundingClientRect(); return { left: rect.left, right: rect.right, top: rect.top, width: rect.width };
      }) };
  });
  expect(layout.scrollWidth).toBeLessThanOrEqual(layout.width);
  expect(layout.dice).toHaveLength(12);
  expect(layout.sideVisible).toBe(true);
  expect(new Set(layout.dice.map((die) => Math.round(die.top))).size).toBe(1);
  for (let i = 1; i < layout.dice.length; i++) expect(layout.dice[i].left).toBeGreaterThanOrEqual(layout.dice[i - 1].right);
  for (const die of layout.dice) { expect(die.width).toBeGreaterThanOrEqual(20); expect(die.width).toBeLessThanOrEqual(28); }
  if (layout.available < 800) {
    const header = [layout.start, layout.outcome, layout.duration];
    expect(Math.max(...header.map((item) => item.center)) - Math.min(...header.map((item) => item.center))).toBeLessThan(4);
    for (let i = 1; i < header.length; i++) expect(header[i].left).toBeGreaterThanOrEqual(header[i - 1].right);
    expect(Math.abs((layout.outcome.left + layout.outcome.right) / 2 - layout.centerX)).toBeLessThan(1);
    expect(layout.scores.top).toBeGreaterThan(layout.outcome.bottom);
    if (layout.available < 480) {
      expect(layout.player.top).toBeGreaterThanOrEqual(layout.scores.bottom);
    } else {
      expect(layout.player.right).toBeLessThanOrEqual(layout.scores.left);
      expect(layout.scores.right).toBeLessThanOrEqual(layout.opponent.left);
      expect(Math.abs(layout.player.center - layout.scores.center)).toBeLessThan(2);
      expect(Math.abs((layout.player.left + layout.opponent.right) / 2 - layout.centerX)).toBeLessThan(1);
    }
  } else {
    expect(layout.start.right).toBeLessThanOrEqual(layout.player.left);
    expect(layout.player.right).toBeLessThanOrEqual(layout.scores.left);
    expect(layout.scores.right).toBeLessThanOrEqual(layout.opponent.left);
    const remainingCenter = (layout.time.right + layout.columnGap + layout.contentRight) / 2;
    expect(Math.abs((layout.player.left + layout.opponent.right) / 2 - remainingCenter)).toBeLessThan(1);
    expect(layout.outcome.bottom).toBeLessThanOrEqual(layout.scores.top);
  }
  const ordinary = (await page.locator('[data-history-record]').nth(1).boundingBox())!;
  expect(ordinary.height).toBeLessThan(layout.available < 480 ? 164 : layout.available < 800 ? 128 : 104);
}

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  const common = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/common.json`, import.meta.url), 'utf8'));
  const words = common.farkle, touch = width === 390;
  test.describe(`Farkle history ${locale} ${width}`, () => {
    test.use({ viewport: { width, height: touch ? 844 : 900 }, hasTouch: touch });
    const press = (locator: Locator) => touch ? locator.tap() : locator.click();
    const sidebar = (page: Page) => page.locator('.farkle-sidebar');
    const table = (page: Page) => page.locator('.farkle-table');
    const dialog = (page: Page) => page.getByRole('dialog');
    async function menu(page: Page, name: string) {
      await openSidebar(page);
      await press(sidebar(page).getByRole('button', { name, exact: true }));
    }
    async function start(page: Page, custom = false) {
      await menu(page, custom ? words.customGame : words.newGame);
      if (custom) {
        await dialog(page).getByLabel(words.targetScore, { exact: true }).fill('100');
        await press(dialog(page).getByRole('button', { name: words.opponentModes.custom, exact: true }));
        await press(dialog(page).getByRole('button', { name: words.chooseOpponentDice, exact: true }));
        await press(dialog(page).getByRole('button', { name: words.choosePlayerDice, exact: true }));
      } else await press(dialog(page).getByRole('button', { name: words.chooseDice, exact: true }));
      await press(dialog(page).getByRole('button', { name: words.startGame, exact: true }));
      await expect(table(page)).toHaveAttribute('data-phase', 'idle');
    }
    async function selectAll(page: Page) {
      for (let i = 0; i < 6; i++) await press(page.locator(`[data-die-id="B${i}"]`));
    }
    async function win(page: Page) {
      await selectAll(page);
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await expect(dialog(page).getByRole('heading')).toHaveText(words.youWin);
    }
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((value) => {
        localStorage.setItem('cogita.locale', value);
        Math.random = () => 0;
      }, locale);
      await page.goto('/playground/farkle');
    });

    test('history rows, names, exact large scores and paginated navigation', async ({ page }, info) => {
      const records = Array.from({ length: 41 }, (_, i) => ({ ...example, startedAt: startedAt - i * 700000,
        level: i % 2 ? 'burgomasters' as const : null, winner: i % 2 ? 'A' as const : 'B' as const }));
      records[0] = { ...records[0], playerScore: overshootScore, targetScore: Number.MAX_SAFE_INTEGER - 1 };
      await page.evaluate(({ key, raw }) => localStorage.setItem(key, raw), { key: HISTORY_KEY, raw: encode(records) });
      await page.reload();
      await openSidebar(page);
      const entries = await sidebar(page).locator('[data-slot="sidebar-header"] [data-slot="sidebar-menu-button"]').allTextContents();
      expect(entries.indexOf(words.history)).toBe(entries.indexOf(words.customGame) + 1);
      await press(sidebar(page).getByRole('button', { name: words.history, exact: true }));
      await expect(page).toHaveURL('/playground/farkle?view=history&page=1');
      await expect(table(page)).toBeHidden();
      const rows = page.locator('[data-history-record]'), first = rows.first();
      await expect(rows).toHaveCount(20);
      await expect(page.locator('.farkle-history table')).toHaveCount(0);
      await expect(first.locator('[data-history-score="player"]')).toHaveText(String(overshootScore));
      await expect(rows.locator('[data-slot="badge"]')).toHaveCount(0);
      await expect(first.locator('[data-history-goal-label]')).toHaveText(words.historyCustom);
      await expect(rows.nth(1).locator('[data-history-goal-label]')).toHaveText(words.goal);
      const playerDice = first.getByRole('group', { name: words.player, exact: true }).locator('[data-history-die]');
      expect(await playerDice.evaluateAll((nodes) => nodes.map((node) => [node.getAttribute('data-history-die'), node.getAttribute('data-preview-face')]))).toEqual([
        ['aranka', '1'], ['devil', '2'], ['lu', '3'], ['normal', '4'], ['normal', '5'], ['weighted', '6'],
      ]);
      if (touch) await playerDice.first().tap(); else await playerDice.first().hover();
      const card = page.locator('[data-slot="hover-card-content"]');
      await expect(card).toHaveText(words.dice.aranka);
      expect(await card.evaluate((node) => getComputedStyle(node).whiteSpace)).toBe('nowrap');
      if (!touch) {
        await page.mouse.move(1, 1);
        await expect(card).toHaveCount(0);
        await playerDice.nth(1).focus();
        await expect(card).toHaveText(words.dice.devil);
      }
      await press(page.locator('[data-slot="pagination-link"]').filter({ hasText: /^2$/ }));
      await expect(page).toHaveURL('/playground/farkle?view=history&page=2');
      await expect(rows).toHaveCount(20);
      await expect(rows.first()).toHaveAttribute('data-started-at', String(records[20].startedAt));
      await page.reload();
      await expect(rows.first()).toHaveAttribute('data-started-at', String(records[20].startedAt));
      await page.goBack();
      await expect(rows.first()).toHaveAttribute('data-started-at', String(records[0].startedAt));
      await page.goForward();
      await press(page.locator('[data-slot="pagination-link"]').filter({ hasText: /^3$/ }));
      await expect(rows).toHaveCount(1);
      await expect(page.getByRole('link', { name: common.pagination.next })).toHaveAttribute('aria-disabled', 'true');
      await menu(page, words.history);
      await expect(rows).toHaveCount(20);
      expect(await page.locator('[data-history-scroll]').evaluate((node) => node.scrollTop)).toBe(0);
      await expect(page.locator('.topbar h1')).toBeInViewport();
      await expect(page.getByRole('navigation', { name: common.pagination.label })).toBeInViewport();
      expect(await page.locator('.farkle-history').evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
      expect(await first.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
      if (touch) {
        const boxes = await playerDice.evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().toJSON()));
        expect(new Set(boxes.map((box) => box.y)).size).toBe(1);
        for (const box of boxes) expect(box.height).toBeGreaterThanOrEqual(44);
      }
      await page.screenshot({ path: info.outputPath('history.png') });
      // The same desktop viewport changes layout when the sidebar consumes content width.
      if (await page.locator('[data-sidebar="trigger"]').getAttribute('aria-expanded') === 'true') {
        await press(page.locator('[data-sidebar="trigger"]'));
      }
      for (const available of [320, 390, 479, 480, 560, 799, 800, 1000]) {
        await page.setViewportSize({ width: available, height: 844 });
        if (await page.locator('[data-sidebar="trigger"]').getAttribute('aria-expanded') === 'true') {
          await press(page.locator('[data-sidebar="trigger"]'));
        }
        await expect.poll(() => page.locator('.farkle-history').evaluate((node) => node.clientWidth)).toBe(available);
        await expect(() => expectResponsiveRecord(page)).toPass({ timeout: 5000 });
        if ([320, 560, 800].includes(available)) await page.screenshot({ path: info.outputPath(`history-layout-${available}.png`) });
      }
      await openSidebar(page);
      await expect.poll(() => page.locator('.farkle-history').evaluate((node) => node.clientWidth)).toBe(744);
      await expect(() => expectResponsiveRecord(page)).toPass({ timeout: 5000 });
      if (touch) {
        const full = Array.from({ length: 100 }, (_, i) => ({ ...example, startedAt: startedAt - i * 700000 }));
        await page.evaluate(({ key, raw }) => localStorage.setItem(key, raw), { key: HISTORY_KEY, raw: encode(full) });
        await page.setViewportSize({ width: 320, height: 740 });
        await page.reload();
        await expect(page.getByRole('link', { name: '5', exact: true })).toBeVisible();
        for (const target of [first, page.locator('.farkle-history'), page.getByRole('navigation', { name: common.pagination.label })]) {
          expect(await target.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
        }
        await page.screenshot({ path: info.outputPath('history-320.png') });
        await page.setViewportSize({ width: 844, height: 390 });
        await openSidebar(page);
        const footer = sidebar(page).getByRole('button', { name: words.backToTable, exact: true });
        const box = (await footer.boundingBox())!;
        expect(box.y + box.height).toBeLessThanOrEqual(390);
        await sidebar(page).getByRole('button', { name: words.settings, exact: true }).scrollIntoViewIfNeeded();
        await expect(footer).toBeInViewport();
        await page.setViewportSize({ width: 1300, height: 844 });
        await expect(first).toBeInViewport();
        expect(await first.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
      }
      await menu(page, words.backToTable);
      await expect(page).toHaveURL('/playground/farkle');
      await expect(table(page)).toBeVisible();
      await openSidebar(page);
      await expect(sidebar(page).getByRole('button', { name: common.back, exact: true })).toBeEnabled();
    });

    test('ordinary settlement keeps the opening mode, elapsed time and game state across history', async ({ page }) => {
      await page.clock.setFixedTime(new Date(startedAt));
      await start(page);
      const openingDice = await page.locator('[data-die-id]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-die-type')));
      await menu(page, words.settings);
      await press(dialog(page).getByRole('button', { name: words.opponentModes.wild, exact: true }));
      await page.keyboard.press('Escape');
      await menu(page, words.history);
      await expect(page.getByText(words.historyEmpty, { exact: true })).toBeVisible();
      await page.clock.setFixedTime(new Date(startedAt + 72000));
      await page.keyboard.press('q');
      expect(await saved(page)).toEqual([]);
      await menu(page, words.backToTable);
      await expect(page).toHaveURL('/playground/farkle');
      if (touch) await expect(page.locator('[data-sidebar="trigger"]')).toHaveAttribute('aria-expanded', 'false');
      expect(await page.locator('[data-die-id]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-die-type')))).toEqual(openingDice);
      await win(page);
      await expect.poll(async () => (await saved(page)).length).toBe(1);
      const [record] = await saved(page);
      expect(record).toMatchObject({ startedAt, durationSeconds: 72, opponentMode: 'dynamic', level: 'beggars', winner: 'B',
        playerTurns: 1, opponentTurns: 0, playerRolls: 1, opponentRolls: 0, playerScore: 8000, opponentScore: 0, targetScore: 1500 });
      await page.keyboard.press('Escape');
      await menu(page, words.history);
      await press(page.locator('.topbar').getByRole('button', { name: words.backToTable, exact: true }));
      await expect(dialog(page)).toHaveCount(0);
      expect(await saved(page)).toEqual([record]);
      await page.reload();
      expect(await saved(page)).toEqual([record]);
      await expect(page.locator('[data-die-id]')).toHaveCount(0);
    });

    test('custom games save without rewards and unfinished games create no record', async ({ page }) => {
      await start(page, true);
      await menu(page, words.exitGame);
      expect(await saved(page)).toEqual([]);
      await start(page, true);
      await page.reload();
      expect(await saved(page)).toEqual([]);
      await start(page, true);
      await win(page);
      await expect.poll(async () => (await saved(page)).length).toBe(1);
      expect((await saved(page))[0]).toMatchObject({ level: null, opponentMode: 'custom', targetScore: 100, winner: 'B' });
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'))).toBeNull();
    });

    test('opponent turns pause in history and defeats save both sides counters', async ({ page }) => {
      await start(page);
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await expect(table(page)).toHaveAttribute('data-player', 'A');
      await menu(page, words.history);
      await expect(table(page)).toHaveAttribute('data-phase', 'idle');
      const selected = await page.locator('[data-state="selected"]').count();
      await page.waitForTimeout(1800);
      expect(await page.locator('[data-state="selected"]').count()).toBe(selected);
      expect(await saved(page)).toEqual([]);
      await press(page.locator('.topbar').getByRole('button', { name: words.backToTable, exact: true }));
      await expect(dialog(page).getByRole('heading')).toHaveText(words.youLost);
      await expect.poll(async () => (await saved(page)).length).toBe(1);
      expect((await saved(page))[0]).toMatchObject({ winner: 'A', playerScore: 0, playerTurns: 1, opponentTurns: 1, playerRolls: 1, opponentRolls: 1 });
    });

    test('failed history saves retry the same record without repeating rewards', async ({ page }) => {
      await page.evaluate((key) => {
        const original = Storage.prototype.setItem;
        let fail = true;
        Storage.prototype.setItem = function (name, value) {
          if (name === key && fail) { fail = false; throw new DOMException('Test quota', 'QuotaExceededError'); }
          original.call(this, name, value);
        };
      }, HISTORY_KEY);
      await start(page);
      await win(page);
      await expect(dialog(page).getByRole('alert')).toContainText(words.historySaveError);
      await expect(dialog(page).getByRole('button', { name: words.playAgain, exact: true })).toBeDisabled();
      const reward = await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'));
      expect(await saved(page)).toEqual([]);
      await page.keyboard.press('Escape');
      await openSidebar(page);
      await expect(sidebar(page).getByRole('button', { name: words.exitGame, exact: true })).toBeDisabled();
      await press(sidebar(page).getByRole('button', { name: words.history, exact: true }));
      await expect(page.locator('[data-history-record]')).toHaveCount(1);
      const before = await page.locator('[data-history-record]').textContent();
      await menu(page, words.backToTable);
      await expect(page).toHaveURL('/playground/farkle');
      await expect(page.getByRole('alert')).toContainText(words.historySaveError);
      await menu(page, words.history);
      await press(page.getByRole('alert').getByRole('button', { name: words.retryStorage, exact: true }));
      expect(await saved(page)).toHaveLength(1);
      await expect(page.locator('[data-history-record]')).toHaveText(before!);
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'))).toBe(reward);
      await page.reload();
      await expect(page.locator('[data-history-record]')).toHaveCount(1);
    });

    test('history read errors and pending saves are cleared by cache reset', async ({ page }) => {
      await page.evaluate((key) => { localStorage.setItem(key, '{broken'); localStorage.setItem('unrelated', 'retained'); }, HISTORY_KEY);
      await page.reload();
      await menu(page, words.history);
      await expect(page.getByRole('alert')).toContainText(words.historyLoadError);
      expect(await page.evaluate((key) => localStorage.getItem(key), HISTORY_KEY)).toBe('{broken');
      await menu(page, words.newGame);
      await expect(dialog(page).getByRole('button', { name: words.chooseDice, exact: true })).toBeDisabled();
      await page.keyboard.press('Escape');
      await expect(dialog(page)).toHaveCount(0);
      await page.evaluate((key) => localStorage.removeItem(key), HISTORY_KEY);
      await press(page.getByRole('alert').getByRole('button', { name: words.retryStorage, exact: true }));
      await expect(page.getByRole('alert')).toHaveCount(0);
      await start(page, true);
      await page.evaluate((key) => {
        const original = Storage.prototype.setItem;
        Storage.prototype.setItem = function (name, value) {
          if (name === key) throw new DOMException('Test quota', 'QuotaExceededError');
          original.call(this, name, value);
        };
      }, HISTORY_KEY);
      await win(page);
      await page.keyboard.press('Escape');
      await menu(page, words.settings);
      await page.evaluate((key) => {
        const original = Storage.prototype.removeItem;
        let fail = true;
        Storage.prototype.removeItem = function (name) {
          if (name === key && fail) { fail = false; throw new DOMException('denied', 'SecurityError'); }
          original.call(this, name);
        };
      }, HISTORY_KEY);
      await press(dialog(page).getByRole('button', { name: words.clearCache, exact: true }));
      const resetError = dialog(page).getByRole('alert').filter({ hasText: words.clearCacheError });
      await expect(resetError).toBeVisible();
      await press(resetError.getByRole('button', { name: words.retryStorage, exact: true }));
      await menu(page, words.history);
      await expect(page.getByText(words.historyEmpty, { exact: true })).toBeVisible();
      expect(await saved(page)).toEqual([]);
      await expect(page.getByRole('alert')).toHaveCount(0);
      expect(await page.evaluate(() => localStorage.getItem('unrelated'))).toBe('retained');
      expect(await page.evaluate(() => localStorage.getItem('cogita.locale'))).toBe(locale);
    });

    test('a winning animation saves in history and defers its result until returning', async ({ page }) => {
      test.skip(touch, 'Uses the visible desktop sidebar to navigate during a storage animation.');
      await start(page, true);
      await selectAll(page);
      await page.evaluate(({ pass, history }) => {
        const button = (root: string, text: string) => [...document.querySelectorAll<HTMLButtonElement>(`${root} button`)].find((node) => node.textContent?.includes(text))!;
        button('.farkle-actions', pass).click();
        button('.farkle-sidebar', history).click();
      }, { pass: words.pass, history: words.history });
      await expect(page).toHaveURL('/playground/farkle?view=history&page=1');
      await expect.poll(async () => (await saved(page)).length).toBe(1);
      await expect(dialog(page)).toHaveCount(0);
      await press(page.locator('.topbar').getByRole('button', { name: words.backToTable, exact: true }));
      await expect(dialog(page).getByRole('heading')).toHaveText(words.youWin);
    });
  });
}
