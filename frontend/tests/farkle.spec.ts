import { readFileSync } from 'node:fs';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { openSidebar } from './controls';

for (const locale of ['en', 'zh-CN']) for (const width of [1366, 390]) {
  const common = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${locale}/common.json`, import.meta.url), 'utf8'));
  const words = common.farkle;
  test.describe(`Farkle ${locale} ${width}`, () => {
    const touch = width === 390;
    test.use({ viewport: { width, height: touch ? 844 : 900 }, hasTouch: touch });
    const sidebar = (page: Page) => page.locator('.farkle-sidebar');
    const table = (page: Page) => page.locator('.farkle-table');
    const die = (page: Page, id: string) => page.locator(`[data-die-id="${id}"]`);
    const score = (page: Page, player: string, row: string) => page.locator(`[data-score="${player}-${row}"]`);
    const total = (page: Page, player: string) => page.locator(`.farkle-score-${player === 'B' ? 'player' : 'opponent'} .farkle-score-total`);
    const press = async (locator: Locator) => { if (touch) await locator.tap(); else await locator.click(); };
    const useFace = (page: Page, face: number) => page.evaluate((value) => { Math.random = () => (value - 0.5) / 6; }, face);
    async function menu(page: Page, label: string) {
      await openSidebar(page);
      await press(sidebar(page).getByRole('button', { name: label, exact: true }));
    }
    async function settled(page: Page) { await expect(table(page)).toHaveAttribute('data-busy', 'false'); }
    async function start(page: Page, level = 'beggars') {
      await menu(page, words.newGame);
      const modal = page.getByRole('dialog', { name: words.newGame, exact: true });
      await press(modal.getByRole('button', { name: new RegExp(words.levels[level]) }));
      await press(modal.getByRole('button', { name: words.startGame, exact: true }));
      await expect(table(page)).toHaveAttribute('data-phase', 'roll');
      await settled(page);
      await expect(page.locator('[data-die-id]')).toHaveCount(6);
    }
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((value) => {
        localStorage.setItem('cogita.locale', value);
        Math.random = () => 0.7;
      }, locale);
      await page.goto('/playground/farkle');
    });
    test('inventory, shop and all four match targets', async ({ page }) => {
      await expect(table(page).locator('canvas')).toHaveCount(1);
      await expect(page.locator('.farkle-hud')).toHaveCount(0);
      await menu(page, words.myDice);
      const inventory = page.getByRole('dialog', { name: words.myDice, exact: true });
      await expect(inventory.locator('li')).toHaveCount(6);
      await expect(inventory.locator('img')).toHaveCount(6);
      await page.keyboard.press('Escape');
      if (touch) await expect(page.locator('[data-sidebar="trigger"]')).toBeFocused();
      else await expect(sidebar(page).getByRole('button', { name: words.myDice, exact: true })).toBeFocused();
      await press(page.getByRole('button', { name: words.balance.replace('{{count}}', '100'), exact: true }));
      await expect(page.getByRole('dialog', { name: words.shop, exact: true })).toHaveCount(1);
      await page.keyboard.press('Escape');
      for (const [level, target] of [['beggars', 1500], ['wagoners', 2000], ['masters', 3000], ['courtiers', 4000]] as const) {
        await start(page, level);
        await expect(page.locator('[data-target-score]')).toHaveText(String(target));
        await expect(page.locator('.farkle-actions button:visible')).toHaveCount(touch ? 2 : 3);
        await expect(page.locator('.farkle-actions kbd')).toHaveText(['E', 'F', 'Q']);
        await expect(page.locator('.farkle-actions button kbd')).toHaveCount(0);
        await expect(page.locator('.farkle-actions kbd:visible')).toHaveCount(touch ? 0 : 3);
        await expect(page.getByRole('button', { name: words.pass, exact: true })).toBeEnabled();
        await expect(page.getByRole('button', { name: words.scoreContinue, exact: true })).toBeDisabled();
        await expect(page.locator('.farkle-score-player .farkle-score-total')).toHaveText('0');
      }
    });
    test('mouse or touch selection, sorted batch rows, reroll, reset and exit', async ({ page }, testInfo) => {
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await start(page, 'masters');
      const first = die(page, 'B0');
      const before = (await first.boundingBox())!;
      const hold = page.getByRole('button', { name: words.hold, exact: true });
      if (touch) {
        await expect(page.locator('[data-hovered="true"]')).toHaveCount(0);
        await expect(page.locator('.farkle-face-icon')).toHaveCount(0);
        await expect(hold).toBeHidden();
        await first.tap();
      } else {
        await first.hover();
        await expect(first).toHaveAttribute('data-hovered', 'true');
        await expect(page.locator('.farkle-face-icon')).toHaveAttribute('data-face-value', (await first.getAttribute('data-value'))!);
        await hold.click();
      }
      await expect(first).toHaveAttribute('aria-pressed', 'true');
      const after = (await first.boundingBox())!;
      expect(Math.abs(after.x - before.x) + Math.abs(after.y - before.y)).toBeLessThan(0.5);
      await press(first);
      await expect(first).toHaveAttribute('aria-pressed', 'false');
      await press(first);
      await page.screenshot({ path: testInfo.outputPath('selected.png') });
      await press(page.getByRole('button', { name: words.scoreContinue, exact: true }));
      await expect(table(page)).toHaveAttribute('data-busy', 'true');
      await settled(page);
      await expect(first).toHaveAttribute('data-state', 'scored');
      await expect(first).toHaveAttribute('data-batch', '0');
      if (touch) await expect(first).toBeHidden();
      else await expect(first).toBeDisabled();
      const firstStored = await first.boundingBox();
      const expected: number[] = [];
      for (const id of ['B3', 'B1', 'B2']) {
        expected.push(Number(await die(page, id).getAttribute('data-value')));
        await press(die(page, id));
      }
      await press(page.getByRole('button', { name: words.scoreContinue, exact: true }));
      await settled(page);
      const second = page.locator('[data-batch="1"]');
      await expect(second).toHaveCount(3);
      if (!touch) {
        const positions = await second.evaluateAll((nodes) => nodes.map((node) => {
          const box = node.getBoundingClientRect();
          return { x: box.x + box.width / 2, y: box.y + box.height / 2, value: Number(node.getAttribute('data-value')) };
        }));
        positions.sort((a, b) => a.x - b.x);
        expect(positions.map((item) => item.value)).toEqual(expected.sort((a, b) => a - b));
        expect(Math.max(...positions.map((item) => item.y)) - Math.min(...positions.map((item) => item.y))).toBeLessThan(8);
        expect(await first.boundingBox()).toEqual(firstStored);
      }
      await page.screenshot({ path: testInfo.outputPath('batches.png') });
      for (const id of ['B4', 'B5']) await press(die(page, id));
      await press(page.getByRole('button', { name: words.scoreContinue, exact: true }));
      await settled(page);
      await expect(page.locator('[data-state="idle"]')).toHaveCount(6);
      await expect(page.locator('[data-batch="-1"]')).toHaveCount(6);
      await menu(page, words.switchView);
      await settled(page);
      await expect(table(page)).toHaveAttribute('data-player', 'B');
      await expect(table(page)).toHaveAttribute('data-view', 'A');
      await expect(die(page, 'A0')).toBeDisabled();
      await expect(page.getByRole('button', { name: words.pass, exact: true })).toBeDisabled();
      await menu(page, words.switchView);
      await settled(page);
      await expect(page.locator('[data-state="selected"]')).toHaveCount(0);
      await start(page);
      await menu(page, words.exitGame);
      await expect(page.locator('[data-die-id]')).toHaveCount(0);
      await expect(page.locator('.farkle-hud')).toHaveCount(0);
      await menu(page, common.back);
      await expect(page).toHaveURL('/playground');
      await page.goBack();
      await expect(page.locator('[data-die-id]')).toHaveCount(0);
      await start(page);
      await page.reload();
      await expect(page.locator('[data-die-id]')).toHaveCount(0);
      expect(errors).toEqual([]);
    });
    test('keyboard navigation, repeat suppression and overlay isolation', async ({ page }) => {
      test.skip(touch, 'Touch selection is covered with real taps.');
      await start(page);
      const hovered = page.locator('[data-hovered="true"]');
      await expect(hovered).toHaveCount(1);
      await page.keyboard.press('e');
      await expect(hovered).toHaveAttribute('aria-pressed', 'true');
      await page.keyboard.down('e');
      await expect(hovered).toHaveAttribute('aria-pressed', 'false');
      await page.keyboard.down('e');
      await expect(hovered).toHaveAttribute('aria-pressed', 'false');
      await page.keyboard.up('e');
      for (const key of ['w', 'a', 's', 'd']) {
        const prior = (await hovered.boundingBox())!;
        await page.keyboard.press(key);
        const next = (await hovered.boundingBox())!;
        if (key === 'w') expect(next.y).toBeLessThanOrEqual(prior.y + 3);
        if (key === 's') expect(next.y).toBeGreaterThanOrEqual(prior.y - 3);
        if (key === 'a') expect(next.x).toBeLessThanOrEqual(prior.x + 3);
        if (key === 'd') expect(next.x).toBeGreaterThanOrEqual(prior.x - 3);
      }
      await page.keyboard.press('e');
      await expect(page.locator('[data-state="selected"]')).toHaveCount(1);
      await page.keyboard.press('f');
      await settled(page);
      await expect(page.locator('[data-state="scored"]')).toHaveCount(1);
      await expect(hovered).not.toHaveAttribute('data-state', 'scored');
      await menu(page, words.myDice);
      for (const key of ['e', 'f', 'q']) await page.keyboard.press(key);
      await expect(page.locator('[data-state="selected"]')).toHaveCount(0);
      await expect(page.locator('[data-state="scored"]')).toHaveCount(1);
      await page.keyboard.press('Escape');
      await page.keyboard.press('q');
      await settled(page);
      await expect(table(page)).toHaveAttribute('data-player', 'A');
      await expect(total(page, 'B')).toHaveText('50');
    });
    test('live scores, observation isolation and passes with or without a selection', async ({ page }, testInfo) => {
      await start(page);
      await press(die(page, 'B0'));
      await expect(score(page, 'B', 'selected')).toHaveText('50');
      await menu(page, words.switchView);
      await settled(page);
      await expect(score(page, 'B', 'selected')).toHaveText('50');
      await expect(page.locator('[data-die-id]:enabled')).toHaveCount(0);
      for (const key of ['e', 'f', 'q']) await page.keyboard.press(key);
      await expect(table(page)).toHaveAttribute('data-player', 'B');
      await menu(page, words.switchView);
      await settled(page);
      await expect(die(page, 'B0')).toHaveAttribute('aria-pressed', 'true');
      await press(page.getByRole('button', { name: words.scoreContinue, exact: true }));
      await settled(page);
      await expect(score(page, 'B', 'round')).toHaveText('50');
      await expect(score(page, 'B', 'selected')).toHaveText('0');
      await press(die(page, 'B1'));
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await settled(page);
      await expect(table(page)).toHaveAttribute('data-player', 'A');
      await expect(table(page)).toHaveAttribute('data-view', 'A');
      await expect(total(page, 'B')).toHaveText('100');
      await expect(score(page, 'B', 'round')).toHaveText('0');
      await expect(score(page, 'B', 'selected')).toHaveText('0');
      for (const id of ['A0', 'A1', 'A2']) await press(die(page, id));
      await expect(score(page, 'A', 'selected')).toHaveText('500');
      await page.screenshot({ path: testInfo.outputPath('opponent-selected.png') });
      await press(page.getByRole('button', { name: words.scoreContinue, exact: true }));
      await settled(page);
      await expect(score(page, 'A', 'round')).toHaveText('500');
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await settled(page);
      await expect(total(page, 'A')).toHaveText('500');
      await expect(table(page)).toHaveAttribute('data-player', 'B');
      await expect(page.locator('[data-state="idle"]')).toHaveCount(6);
      await expect(page.locator('[data-batch="-1"]')).toHaveCount(6);
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await settled(page);
      await expect(table(page)).toHaveAttribute('data-player', 'A');
      await expect(total(page, 'B')).toHaveText('100');
      await expect(page.locator('[data-state="idle"]')).toHaveCount(6);
    });
    test('wildcard restrictions, winning empty pass, frozen result and new-game settings', async ({ page }, testInfo) => {
      await useFace(page, 1);
      await start(page, 'courtiers');
      const head = die(page, 'B1');
      await expect(head).toHaveAccessibleName(new RegExp(words.wildFace));
      if (!touch) {
        await head.hover();
        await expect(page.locator('.farkle-face-icon')).toHaveAttribute('data-face-value', 'wild');
      }
      await press(head);
      const storeButton = page.getByRole('button', { name: words.scoreContinue, exact: true });
      const passButton = page.getByRole('button', { name: words.pass, exact: true });
      await expect(score(page, 'B', 'selected')).toHaveText('0');
      await expect(storeButton).toBeDisabled();
      await expect(passButton).toBeDisabled();
      await press(die(page, 'B0'));
      await expect(score(page, 'B', 'selected')).toHaveText('0');
      await expect(passButton).toBeDisabled();
      await press(die(page, 'B2'));
      await expect(score(page, 'B', 'selected')).toHaveText('1000');
      await press(head);
      await expect(score(page, 'B', 'selected')).toHaveText('200');
      await press(head);
      for (const id of ['B3', 'B4', 'B5']) await press(die(page, id));
      await expect(score(page, 'B', 'selected')).toHaveText('8000');
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await press(storeButton);
      await settled(page);
      await expect(score(page, 'B', 'round')).toHaveText('8000');
      await expect(total(page, 'B')).toHaveText('0');
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await press(passButton);
      const result = page.getByRole('dialog', { name: words.result, exact: true });
      await expect(result).toBeVisible();
      await expect(result).toContainText(words.winner.replace('{{player}}', words.player));
      await expect(result.locator('[data-result-score="B"]')).toHaveText('8000');
      await expect(table(page)).toHaveAttribute('data-phase', 'finished');
      await expect(table(page)).toHaveAttribute('data-view', 'B');
      await page.screenshot({ path: testInfo.outputPath('result.png') });
      await press(result.getByRole('button', { name: words.newGame, exact: true }));
      const settings = page.getByRole('dialog', { name: words.newGame, exact: true });
      await expect(settings.getByRole('button', { name: new RegExp(words.levels.courtiers) })).toHaveAttribute('aria-pressed', 'true');
      await page.keyboard.press('Escape');
      await expect(page.locator('[data-sidebar="trigger"]')).toBeFocused();
      for (const key of ['e', 'f', 'q', 'w', 'a', 's', 'd']) await page.keyboard.press(key);
      await expect(table(page)).toHaveAttribute('data-phase', 'finished');
      await expect(page.locator('[data-die-id]:enabled')).toHaveCount(0);
      await expect(page.locator('.farkle-actions button:enabled')).toHaveCount(0);
      await expect(total(page, 'B')).toHaveText('8000');
      await openSidebar(page);
      await expect(sidebar(page).getByRole('button', { name: words.switchView, exact: true })).toBeDisabled();
      await press(sidebar(page).getByRole('button', { name: words.newGame, exact: true }));
      await press(settings.getByRole('button', { name: words.startGame, exact: true }));
      await settled(page);
      await expect(total(page, 'B')).toHaveText('0');
      await expect(table(page)).toHaveAttribute('data-phase', 'idle');
    });
    test('opponent wins with selected dice and replay retains the match level', async ({ page }) => {
      await start(page, 'masters');
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await settled(page);
      for (let index = 0; index < 6; index++) await press(die(page, `A${index}`));
      await expect(score(page, 'A', 'selected')).toHaveText('4000');
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      const result = page.getByRole('dialog', { name: words.result, exact: true });
      await expect(result).toBeVisible();
      await expect(result).toContainText(words.winner.replace('{{player}}', words.opponent));
      await expect(result.locator('[data-result-score="A"]')).toHaveText('4000');
      await expect(table(page)).toHaveAttribute('data-view', 'A');
      await expect(table(page)).toHaveAttribute('data-phase', 'finished');
      await press(result.getByRole('button', { name: words.playAgain, exact: true }));
      await settled(page);
      await expect(table(page)).toHaveAttribute('data-player', 'B');
      await expect(table(page)).toHaveAttribute('data-view', 'B');
      await expect(page.locator('[data-target-score]')).toHaveText('3000');
      await expect(total(page, 'A')).toHaveText('0');
      await expect(total(page, 'B')).toHaveText('0');
      await expect(page.locator('[data-state="idle"]')).toHaveCount(6);
      await expect(page.getByRole('dialog')).toHaveCount(0);
    });
    test('bust loses an unbanked winning round and automatically hands off', async ({ page }, testInfo) => {
      await start(page);
      for (let index = 0; index < 5; index++) await press(die(page, `B${index}`));
      await expect(score(page, 'B', 'selected')).toHaveText('2000');
      await useFace(page, 2);
      await press(page.getByRole('button', { name: words.scoreContinue, exact: true }));
      await expect(score(page, 'B', 'round')).toHaveText('2000');
      const bust = table(page).getByRole('status');
      await expect(bust).toHaveText(words.bust);
      await expect(score(page, 'B', 'round')).toHaveText('0');
      await expect(total(page, 'B')).toHaveText('0');
      await expect(page.locator('.farkle-actions button:enabled')).toHaveCount(0);
      const placement = await page.evaluate(() => {
        const board = document.querySelector('.farkle-table')!.getBoundingClientRect();
        const text = document.querySelector('.farkle-bust .farkle-score-heading')!;
        const box = text.getBoundingClientRect();
        const heading = getComputedStyle(document.querySelector('.farkle-score .farkle-score-heading')!);
        const style = getComputedStyle(text);
        return { dx: box.x + box.width / 2 - board.x - board.width / 2,
          dy: box.y + box.height / 2 - board.y - board.height / 2,
          actual: [style.fontFamily, style.fontSize, style.fontWeight, style.color, style.textShadow],
          expected: [heading.fontFamily, heading.fontSize, heading.fontWeight, heading.color, heading.textShadow] };
      });
      expect(Math.abs(placement.dx)).toBeLessThan(1);
      expect(Math.abs(placement.dy)).toBeLessThan(1);
      expect(placement.actual).toEqual(placement.expected);
      await page.screenshot({ path: testInfo.outputPath('bust.png') });
      await settled(page);
      await expect(table(page)).toHaveAttribute('data-player', 'A');
      await expect(table(page)).toHaveAttribute('data-view', 'A');
      await expect(page.locator('[data-state="idle"]')).toHaveCount(6);
      await expect(bust).toHaveCount(0);
      await expect(total(page, 'B')).toHaveText('0');
      await expect(page.getByRole('dialog')).toHaveCount(0);
    });
    test('compact HUD at narrow and short sizes', async ({ page }, testInfo) => {
      await start(page);
      for (const viewport of touch ? [{ width: 320, height: 740 }, { width: 844, height: 390 }] : [{ width: 1366, height: 600 }]) {
        await page.setViewportSize(viewport);
        const actions = (await page.locator('.farkle-actions').boundingBox())!;
        const scores = (await page.locator('.farkle-score').boundingBox())!;
        const board = (await table(page).boundingBox())!;
        expect(scores.x + scores.width).toBeLessThanOrEqual(actions.x);
        const textRight = await page.locator('.farkle-score-heading').evaluateAll((nodes) => Math.max(...nodes.map((node) => {
          const range = document.createRange(); range.selectNodeContents(node);
          return range.getBoundingClientRect().right;
        })));
        expect(textRight).toBeLessThanOrEqual(actions.x);
        expect(actions.x + actions.width).toBeLessThanOrEqual(board.x + board.width);
        expect(actions.y + actions.height).toBeLessThanOrEqual(board.y + board.height);
        const actionBoxes = await page.locator('.farkle-actions button:visible').evaluateAll((nodes) => nodes.map((node) => {
          const box = node.getBoundingClientRect(); return { width: box.width, right: box.right, height: box.height };
        }));
        expect(Math.max(...actionBoxes.map((box) => box.right)) - Math.min(...actionBoxes.map((box) => box.right))).toBeLessThan(1);
        expect(Math.max(...actionBoxes.map((box) => box.width)) - Math.min(...actionBoxes.map((box) => box.width))).toBeGreaterThan(10);
        if (touch) for (const button of await page.locator('.farkle-actions button:visible').all())
          expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(44);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight)).toBe(true);
        await page.screenshot({ path: testInfo.outputPath(`hud-${viewport.width}.png`) });
      }
    });
  });
}
