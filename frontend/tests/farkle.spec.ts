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
    async function resultStyle(page: Page, won: boolean) {
      const actual = await page.evaluate((win) => {
        const modal = document.querySelector('.farkle-result')!;
        const title = modal.querySelector('[data-slot="dialog-title"]')!;
        const resultScore = modal.querySelector('[data-result-score]')!;
        const style = (node: Element) => getComputedStyle(node);
        const heading = document.querySelector('.farkle-score-heading')!;
        const total = document.querySelector('.farkle-score-total')!;
        const round = document.querySelector('[data-score="B-round"]')!;
        const color = win ? heading : document.querySelector('.farkle-score-opponent .farkle-score-total')!;
        const font = (node: Element) => [style(node).fontFamily, style(node).fontWeight, style(node).textShadow];
        const center = modal.getBoundingClientRect().x + modal.getBoundingClientRect().width / 2;
        const offset = (node: Element) => {
          const range = document.createRange(); range.selectNodeContents(node);
          const box = range.getBoundingClientRect(); return Math.abs(box.x + box.width / 2 - center);
        };
        return { titleFont: font(title), headingFont: font(heading), scoreFont: font(resultScore), totalFont: font(total),
          titleColor: style(title).color, expectedTitleColor: style(color).color,
          scoreColor: style(resultScore).color, roundColor: style(round).color,
          titleSize: parseFloat(style(title).fontSize), scoreSize: parseFloat(style(resultScore).fontSize),
          centered: [offset(title), offset(resultScore)] };
      }, won);
      expect(actual.titleFont).toEqual(actual.headingFont);
      expect(actual.scoreFont).toEqual(actual.totalFont);
      expect(actual.titleColor).toBe(actual.expectedTitleColor);
      expect(actual.scoreColor).toBe(actual.roundColor);
      expect(actual.titleSize).toBeGreaterThan(actual.scoreSize);
      expect(Math.max(...actual.centered)).toBeLessThan(1);
    }
    const choice = (page: Page) => page.getByRole('dialog', { name: words.chooseDice, exact: true });
    const row = (page: Page, type: string) => choice(page).locator(`[data-inventory-type="${type}"]`);
    const adjust = (page: Page, type: string, add: boolean) => press(row(page, type).getByRole('button', {
      name: (add ? words.addDie : words.removeDie).replace('{{name}}', words.dice[type]), exact: true,
    }));
    async function choose(page: Page, counts?: Record<string, number>) {
      if (counts) {
        for (const item of await choice(page).locator('[data-inventory-type]').all()) {
          const type = (await item.getAttribute('data-inventory-type'))!;
          const count = Number(await item.locator('[data-selected-count]').textContent());
          for (let index = 0; index < count; index++) await adjust(page, type, false);
        }
        for (const [type, count] of Object.entries(counts)) for (let index = 0; index < count; index++) await adjust(page, type, true);
      }
    }
    async function start(page: Page, level = 'beggars', counts?: Record<string, number>) {
      await menu(page, words.newGame);
      const modal = page.getByRole('dialog', { name: words.newGame, exact: true });
      await press(modal.getByRole('button', { name: new RegExp(words.levels[level]) }));
      await press(modal.getByRole('button', { name: words.chooseDice, exact: true }));
      await choose(page, counts);
      await page.evaluate((samples) => {
        const fallback = Math.random;
        Math.random = () => samples.length ? samples.shift()! : fallback();
      }, Array(6).fill(0));
      await press(choice(page).getByRole('button', { name: words.startGame, exact: true }));
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
    test('choose six owned dice, keep drafts when going back, and persist only on start', async ({ page }, testInfo) => {
      await page.evaluate(() => localStorage.setItem('cogita.farkle.inventory', JSON.stringify({
        special: { even: 1, odd: 0, devil: 0, weighted: 0 }, merchant: 2, firstWins: [],
      })));
      await page.reload();
      const inventory = await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'));
      await menu(page, words.newGame);
      await press(page.getByRole('dialog').getByRole('button', { name: words.chooseDice, exact: true }));
      await expect(choice(page).locator('[data-inventory-type]')).toHaveCount(3);
      await expect(row(page, 'normal').locator('[data-selected-count]')).toHaveText('6');
      const addEven = row(page, 'even').getByRole('button', { name: words.addDie.replace('{{name}}', words.dice.even), exact: true });
      await expect(addEven).toBeDisabled();
      await adjust(page, 'normal', false);
      await expect(choice(page).getByRole('button', { name: words.startGame, exact: true })).toBeDisabled();
      await adjust(page, 'even', true);
      await adjust(page, 'normal', false);
      await expect(addEven).toBeDisabled();
      await adjust(page, 'merchant', true);
      await expect(choice(page).locator('[data-loadout-total]')).toHaveText(words.diceSelected.replace('{{count}}', '6'));
      await press(choice(page).getByRole('button', { name: common.back, exact: true }));
      await press(page.getByRole('dialog').getByRole('button', { name: words.chooseDice, exact: true }));
      await expect(row(page, 'normal').locator('[data-selected-count]')).toHaveText('4');
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.loadout'))).toBeNull();
      await page.keyboard.press('Escape');
      await expect(page.locator('[data-die-id]')).toHaveCount(0);
      await start(page, 'masters', { normal: 4, even: 1, merchant: 1 });
      const saved = { normal: 4, even: 1, odd: 0, devil: 0, weighted: 0, merchant: 1 };
      expect(await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.loadout')!))).toEqual(saved);
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'))).toBe(inventory);
      await expect(die(page, 'B4')).toHaveAttribute('data-die-type', 'even');
      await expect(die(page, 'B5')).toHaveAttribute('data-die-type', 'merchant');
      await menu(page, words.newGame);
      await press(page.getByRole('dialog').getByRole('button', { name: words.chooseDice, exact: true }));
      await adjust(page, 'normal', false);
      await page.keyboard.press('Escape');
      await expect(die(page, 'B4')).toHaveAttribute('data-die-type', 'even');
      await page.reload();
      await menu(page, words.newGame);
      await press(page.getByRole('dialog').getByRole('button', { name: words.chooseDice, exact: true }));
      await expect(row(page, 'normal').locator('[data-selected-count]')).toHaveText('4');
      await expect(row(page, 'even').locator('[data-selected-count]')).toHaveText('1');
      await page.screenshot({ path: testInfo.outputPath('choose-dice.png') });
      await page.setViewportSize({ width: touch ? 390 : 1366, height: 320 });
      await expect.poll(() => choice(page).locator('[data-loadout]').evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true);
      const footer = await choice(page).getByRole('button', { name: words.startGame, exact: true }).boundingBox();
      expect(footer!.y + footer!.height).toBeLessThanOrEqual(320);
    });
    test('invalid saved selection defaults to normal dice and failed saving retains the chooser', async ({ page }) => {
      await page.evaluate(() => {
        localStorage.setItem('cogita.farkle.loadout', '{broken');
        const original = Storage.prototype.setItem;
        let fail = true;
        Storage.prototype.setItem = function (key, value) {
          if (key === 'cogita.farkle.loadout' && fail) { fail = false; throw new DOMException('Test quota', 'QuotaExceededError'); }
          original.call(this, key, value);
        };
      });
      await menu(page, words.newGame);
      await press(page.getByRole('dialog').getByRole('button', { name: words.chooseDice, exact: true }));
      await expect(row(page, 'normal').locator('[data-selected-count]')).toHaveText('6');
      await press(choice(page).getByRole('button', { name: words.startGame, exact: true }));
      await expect(choice(page).getByRole('alert')).toContainText(words.loadoutSaveError);
      await expect(page.locator('[data-die-id]')).toHaveCount(0);
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.loadout'))).toBe('{broken');
      await press(choice(page).getByRole('button', { name: words.retryStorage, exact: true }));
      await settled(page);
      await expect(page.locator('[data-die-type="normal"]')).toHaveCount(6);
      expect(await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.loadout')!).normal)).toBe(6);
    });
    test('probability cards on inventory and chooser support mouse, keyboard and touch', async ({ page }, testInfo) => {
      await menu(page, words.myDice);
      const inventoryRow = (type: string) => page.getByRole('dialog').locator(`[data-inventory-type="${type}"]`);
      if (touch) await inventoryRow('normal').locator('img').tap();
      else await inventoryRow('normal').locator('[data-inventory-count]').hover();
      await expect(page.locator('[data-dice-probabilities]')).toHaveCount(0);
      for (const [type, expected] of Object.entries({
        normal: ['16.7%', '16.7%', '16.7%', '16.7%', '16.7%', '16.7%'],
        even: ['6.7%', '26.7%', '6.7%', '26.7%', '6.7%', '26.7%'],
        odd: ['26.7%', '6.7%', '26.7%', '6.7%', '26.7%', '6.7%'],
        weighted: ['66.7%', '6.7%', '6.7%', '6.7%', '6.7%', '6.7%'],
        devil: ['16.7%', '16.7%', '16.7%', '16.7%', '16.7%', '16.7%'],
      })) {
        if (touch) await press(inventoryRow(type).getByRole('button'));
        else {
          await page.mouse.move(0, 0);
          await expect(page.locator('[data-dice-probabilities]')).toHaveCount(0);
          await inventoryRow(type).getByRole('button').hover();
        }
        const card = page.locator(`[data-dice-probabilities="${type}"]`);
        await expect(card).toBeVisible();
        await expect(card).toHaveCSS('opacity', '1');
        await expect(card.locator('[data-probability-face]')).toHaveText(expected);
        const lines = await card.locator('[data-probability-face]').evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().top));
        expect(Math.max(...lines) - Math.min(...lines)).toBeLessThan(1);
        if (type === 'devil') {
          await expect(card.locator('[data-probability-face="1"]')).toHaveAttribute('aria-label', `${words.wildFace}: 16.7%`);
          await page.screenshot({ path: testInfo.outputPath('probabilities.png') });
        }
      }
      if (!touch) {
        await page.mouse.move(0, 0);
        await inventoryRow('normal').getByRole('button').focus();
        await expect(page.locator('[data-dice-probabilities="normal"]')).toBeVisible();
      }
      await page.getByRole('dialog').getByRole('heading').click();
      await page.keyboard.press('Escape');
      await menu(page, words.newGame);
      await press(page.getByRole('dialog').getByRole('button', { name: words.chooseDice, exact: true }));
      const name = row(page, 'normal').getByRole('button', { name: words.dice.normal, exact: true });
      if (touch) await press(name); else await name.hover();
      await expect(page.locator('[data-dice-probabilities="normal"]')).toBeVisible();
      await adjust(page, 'normal', false);
      await expect(row(page, 'normal').locator('[data-selected-count]')).toHaveText('5');
      const positions = await row(page, 'normal').evaluate((node) => {
        const name = node.querySelector('[data-slot="hover-card-trigger"]')!;
        const quantity = node.querySelector('[data-inventory-count]')!;
        return quantity.getBoundingClientRect().left - name.getBoundingClientRect().right;
      });
      expect(positions).toBeGreaterThanOrEqual(0);
      expect(positions).toBeLessThan(12);
    });
    test('idle, exited and finished tables open settings without dismissal click-through', async ({ page }) => {
      const entry = page.locator('[data-table-new-game]');
      if (touch) await entry.tap({ position: { x: 10, y: 10 } });
      else { await entry.focus(); await page.keyboard.press('Enter'); }
      await expect(page.getByRole('dialog', { name: words.newGame, exact: true })).toBeVisible();
      await expect(entry).toHaveCount(0);
      const overlay = page.locator('[data-slot="dialog-overlay"]');
      await overlay.click({ position: { x: 5, y: 5 } });
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await expect(entry).toHaveCount(1);
      await start(page, 'masters');
      await expect(entry).toHaveCount(0);
      await menu(page, words.exitGame);
      await press(entry);
      await expect(page.getByRole('dialog', { name: words.newGame, exact: true })).toBeVisible();
      await page.keyboard.press('Escape');
      await start(page, 'masters');
      for (let index = 0; index < 6; index++) await press(die(page, `B${index}`));
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await expect(page.getByRole('dialog', { name: words.youWin, exact: true })).toBeVisible();
      await page.keyboard.press('Escape');
      await press(entry);
      await expect(page.getByRole('dialog').getByRole('button', { name: new RegExp(words.levels.masters) })).toHaveAttribute('aria-pressed', 'true');
      await expect(table(page)).toHaveAttribute('data-phase', 'finished');
    });
    test('turn notice follows turn ownership and only announces each player turn once', async ({ page }, testInfo) => {
      await menu(page, words.newGame);
      await press(page.getByRole('dialog').getByRole('button', { name: words.chooseDice, exact: true }));
      await press(choice(page).getByRole('button', { name: words.startGame, exact: true }));
      const notice = page.locator('[data-turn-notice]');
      await expect(notice).toHaveText(words.yourTurn);
      const styling = await notice.locator('.farkle-score-heading').evaluate((node) => {
        const actual = getComputedStyle(node), expected = getComputedStyle(document.querySelector('.farkle-score .farkle-score-heading')!);
        const font = (style: CSSStyleDeclaration) => [style.fontFamily, style.fontSize, style.fontWeight, style.color, style.textShadow];
        return { actual: font(actual), expected: font(expected) };
      });
      expect(styling.actual).toEqual(styling.expected);
      await expect(notice).toHaveCount(0);
      await settled(page);
      await menu(page, words.switchView);
      await settled(page);
      await expect(notice).toHaveCount(0);
      await menu(page, words.switchView);
      await settled(page);
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await expect(notice).toHaveText(words.opponentTurn);
      await settled(page);
      await menu(page, words.switchView);
      await settled(page);
      await expect(table(page)).toHaveAttribute('data-view', 'B');
      await expect(notice).toHaveText(words.opponentTurn);
      await page.screenshot({ path: testInfo.outputPath('opponent-turn.png') });
      await menu(page, words.switchView);
      await settled(page);
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await expect(notice).toHaveText(words.yourTurn);
      await expect(notice).toHaveCount(0);
      await menu(page, words.exitGame);
      await expect(notice).toHaveCount(0);
    });
    test('inventory, shop and all four match targets', async ({ page }) => {
      await expect(table(page).locator('canvas')).toHaveCount(1);
      await expect(page.locator('.farkle-hud')).toHaveCount(0);
      await menu(page, words.myDice);
      const inventory = page.getByRole('dialog', { name: words.myDice, exact: true });
      await expect(inventory.locator('li')).toHaveCount(6);
      await expect(inventory.locator('img')).toHaveCount(6);
      await expect(inventory.locator('[data-inventory-count]')).toHaveText(['×6', '0 / 6', '0 / 6', '0 / 6', '0 / 6', '×0']);
      await page.keyboard.press('Escape');
      if (touch) await expect(page.locator('[data-sidebar="trigger"]')).toBeFocused();
      else await expect(sidebar(page).getByRole('button', { name: words.myDice, exact: true })).toBeFocused();
      await press(page.getByRole('button', { name: words.balance.replace('{{count}}', '0'), exact: true }));
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
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'))).toBeNull();
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
      await page.evaluate(() => localStorage.setItem('cogita.farkle.inventory', JSON.stringify({
        special: { even: 0, odd: 0, devil: 1, weighted: 0 }, merchant: 0, firstWins: [],
      })));
      await page.reload();
      await useFace(page, 1);
      await start(page, 'courtiers', { normal: 5, devil: 1 });
      const head = die(page, 'B5');
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
      for (const id of ['B1', 'B3', 'B4']) await press(die(page, id));
      await expect(score(page, 'B', 'selected')).toHaveText('8000');
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await press(storeButton);
      await settled(page);
      await expect(score(page, 'B', 'round')).toHaveText('8000');
      await expect(total(page, 'B')).toHaveText('0');
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await press(passButton);
      const result = page.getByRole('dialog', { name: words.youWin, exact: true });
      await expect(result).toBeVisible();
      await expect(result.getByRole('heading')).toHaveText(words.youWin);
      await expect(result.locator('[data-result-score="B"]')).toHaveText(words.resultScore.replace('{{score}}', '8000'));
      await resultStyle(page, true);
      await expect(result.locator('dl')).toHaveCount(0);
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
      await press(settings.getByRole('button', { name: words.chooseDice, exact: true }));
      await press(choice(page).getByRole('button', { name: words.startGame, exact: true }));
      await settled(page);
      await expect(total(page, 'B')).toHaveText('0');
      await expect(table(page)).toHaveAttribute('data-phase', 'idle');
    });
    test('opponent wins with selected dice and replay retains the match level', async ({ page }, testInfo) => {
      await start(page, 'masters');
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await settled(page);
      for (let index = 0; index < 6; index++) await press(die(page, `A${index}`));
      await expect(score(page, 'A', 'selected')).toHaveText('4000');
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      const result = page.getByRole('dialog', { name: words.youLost, exact: true });
      await expect(result).toBeVisible();
      await expect(result.getByRole('heading')).toHaveText(words.youLost);
      await expect(result.locator('[data-result-score="B"]')).toHaveText(words.resultScore.replace('{{score}}', '0'));
      await expect(result.locator('[data-result-score="A"]')).toHaveCount(0);
      await expect(result.locator('[data-slot="separator"]')).toHaveCount(0);
      await resultStyle(page, false);
      await page.screenshot({ path: testInfo.outputPath('loss.png') });
      const inventory = await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.inventory')!));
      expect(Object.values(inventory.special).reduce((sum: number, count) => sum + Number(count), 0)).toBe(1);
      expect(inventory.merchant).toBe(0);
      expect(inventory.firstWins).toEqual([]);
      await expect(table(page)).toHaveAttribute('data-view', 'A');
      await expect(table(page)).toHaveAttribute('data-phase', 'finished');
      await press(result.getByRole('button', { name: words.playAgain, exact: true }));
      await expect(choice(page)).toBeVisible();
      await expect(row(page, 'normal').locator('[data-selected-count]')).toHaveText('6');
      await expect(table(page)).toHaveAttribute('data-phase', 'finished');
      await adjust(page, 'normal', false);
      await adjust(page, 'devil', true);
      await press(choice(page).getByRole('button', { name: words.startGame, exact: true }));
      await settled(page);
      await expect(table(page)).toHaveAttribute('data-player', 'B');
      await expect(table(page)).toHaveAttribute('data-view', 'B');
      await expect(page.locator('[data-target-score]')).toHaveText('3000');
      await expect(total(page, 'A')).toHaveText('0');
      await expect(total(page, 'B')).toHaveText('0');
      await expect(page.locator('[data-state="idle"]')).toHaveCount(6);
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await expect(page.locator('[data-die-type="devil"]')).toHaveCount(1);
      await expect(page.locator('[data-die-type="normal"]')).toHaveCount(5);
      expect(await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.inventory')!))).toEqual(inventory);
    });
    test('bust loses an unbanked winning round and automatically hands off', async ({ page }, testInfo) => {
      await start(page);
      for (let index = 0; index < 5; index++) await press(die(page, `B${index}`));
      await expect(score(page, 'B', 'selected')).toHaveText('2000');
      await useFace(page, 2);
      await press(page.getByRole('button', { name: words.scoreContinue, exact: true }));
      await expect(score(page, 'B', 'round')).toHaveText('2000');
      const bust = page.locator('.farkle-bust');
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
          size: parseFloat(style.fontSize), headingSize: parseFloat(heading.fontSize),
          actual: [style.fontFamily, style.fontWeight, style.color, style.textShadow],
          expected: [heading.fontFamily, heading.fontWeight, heading.color, heading.textShadow] };
      });
      expect(Math.abs(placement.dx)).toBeLessThan(1);
      expect(Math.abs(placement.dy)).toBeLessThan(1);
      expect(placement.actual).toEqual(placement.expected);
      expect(placement.size).toBeGreaterThan(placement.headingSize);
      expect(placement.size).toBeGreaterThanOrEqual(32);
      expect(placement.size).toBeLessThanOrEqual(64);
      await page.screenshot({ path: testInfo.outputPath('bust.png') });
      await settled(page);
      await expect(table(page)).toHaveAttribute('data-player', 'A');
      await expect(table(page)).toHaveAttribute('data-view', 'A');
      await expect(page.locator('[data-state="idle"]')).toHaveCount(6);
      await expect(bust).toHaveCount(0);
      await expect(total(page, 'B')).toHaveText('0');
      await expect(page.getByRole('dialog')).toHaveCount(0);
    });
    test('six dice types, immutable normal count and hover names', async ({ page }, testInfo) => {
      await page.evaluate(() => localStorage.setItem('cogita.farkle.inventory', JSON.stringify({
        normal: 999, special: { normal: 999, even: 1, odd: 1, devil: 1, weighted: 1 }, merchant: 1, firstWins: [],
      })));
      await page.reload();
      await menu(page, words.myDice);
      await expect(page.locator('[data-inventory-type="normal"] [data-inventory-count]')).toHaveText('×6');
      await page.screenshot({ path: testInfo.outputPath('inventory.png') });
      await page.keyboard.press('Escape');
      await useFace(page, 1);
      await start(page, 'courtiers', { normal: 1, even: 1, odd: 1, devil: 1, weighted: 1, merchant: 1 });
      const types = ['normal', 'even', 'odd', 'devil', 'weighted', 'merchant'];
      for (const [index, type] of types.entries()) {
        await expect(die(page, `B${index}`)).toHaveAttribute('data-die-type', type);
        if (!touch) {
          await die(page, `B${index}`).hover();
          if (type === 'normal') await expect(page.locator('.farkle-die-name')).toHaveCount(0);
          else await expect(page.locator('.farkle-die-name')).toHaveText(words.dice[type]);
        }
      }
      await page.screenshot({ path: testInfo.outputPath('six-types.png') });
      await menu(page, words.newGame);
      await press(page.getByRole('dialog').getByRole('button', { name: words.chooseDice, exact: true }));
      expect(await choice(page).evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath('six-type-chooser.png') });
      await page.keyboard.press('Escape');
      await menu(page, words.exitGame);
      await start(page);
      for (const [index, type] of types.entries()) await expect(die(page, `B${index}`)).toHaveAttribute('data-die-type', type);
    });
    test('first win, overflow conversion, persistence and repeat win', async ({ page }, testInfo) => {
      await page.evaluate(() => localStorage.setItem('cogita.farkle.inventory', JSON.stringify({
        special: { even: 5, odd: 5, devil: 6, weighted: 6 }, merchant: 0, firstWins: [],
      })));
      await page.reload();
      await start(page, 'courtiers');
      for (let index = 0; index < 6; index++) await press(die(page, `B${index}`));
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      const result = page.getByRole('dialog', { name: words.youWin, exact: true });
      await expect(result.locator('[data-reward-group]')).toHaveCount(3);
      await expect(result.locator('[data-slot="separator"]')).toHaveCount(2);
      await expect(result.locator('[data-reward-group="regular"] [data-reward-type="merchant"]')).toContainText('+2');
      await expect(result.locator('[data-reward-group="firstWin"] [data-reward-count]')).toHaveText(words.firstWinAmount.replace('{{count}}', '2'));
      await expect(result.locator('[data-reward-group="converted"] [data-reward-count]')).toHaveText(words.convertedAmount.replace('{{count}}', '1'));
      await expect(page.locator('[data-merchant-balance]')).toHaveText('5');
      await page.screenshot({ path: testInfo.outputPath('rewards.png') });
      const viewport = page.viewportSize()!;
      await page.setViewportSize({ width: touch ? 844 : 1366, height: 320 });
      const rewardBody = result.locator('[data-rewards]');
      await expect.poll(() => rewardBody.evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true);
      await result.locator('[data-reward-group="converted"]').scrollIntoViewIfNeeded();
      const footer = (await result.getByRole('button', { name: words.playAgain, exact: true }).boundingBox())!;
      expect(footer.y + footer.height).toBeLessThanOrEqual(320);
      await page.screenshot({ path: testInfo.outputPath('rewards-short.png') });
      await page.setViewportSize(viewport);
      const saved = await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'));
      expect(JSON.parse(saved!)).toEqual({ special: { even: 6, odd: 6, devil: 6, weighted: 6 }, merchant: 5, firstWins: ['courtiers'] });
      await page.keyboard.press('Escape');
      await menu(page, words.myDice);
      await expect(page.locator('[data-inventory-type="merchant"] [data-inventory-count]')).toHaveText('×5');
      await page.keyboard.press('Escape');
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'))).toBe(saved);
      await page.reload();
      await expect(page.locator('[data-merchant-balance]')).toHaveText('5');
      await expect(page.locator('[data-die-id]')).toHaveCount(0);
      await start(page, 'courtiers');
      for (let index = 0; index < 6; index++) await press(die(page, `B${index}`));
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await expect(result.locator('[data-reward-group="regular"] [data-reward-type="merchant"]')).toContainText('+2');
      await expect(result.locator('[data-slot="separator"]')).toHaveCount(1);
      await expect(result.locator('[data-reward-group="firstWin"]')).toHaveCount(0);
      await expect(result.locator('[data-reward-group="converted"] [data-reward-count]')).toHaveText(words.convertedAmount.replace('{{count}}', '2'));
      await expect(page.locator('[data-merchant-balance]')).toHaveText('9');
    });
    test('failed reward save retries the same settlement once', async ({ page }) => {
      await page.evaluate(() => {
        const original = Storage.prototype.setItem;
        let fail = true;
        Storage.prototype.setItem = function (key, value) {
          if (key === 'cogita.farkle.inventory' && fail) { fail = false; throw new DOMException('Test quota', 'QuotaExceededError'); }
          original.call(this, key, value);
        };
      });
      await start(page);
      for (let index = 0; index < 5; index++) await press(die(page, `B${index}`));
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      const result = page.getByRole('dialog', { name: words.youWin, exact: true });
      await expect(result.getByRole('alert')).toContainText(words.inventorySaveError);
      await expect(result.getByRole('button', { name: words.playAgain, exact: true })).toBeDisabled();
      await expect(result.locator('[data-reward-type="devil"]')).toContainText('+2');
      await expect(result.locator('[data-reward-group]')).toHaveCount(2);
      await expect(result.locator('[data-slot="separator"]')).toHaveCount(1);
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'))).toBeNull();
      const reward = await result.locator('[data-rewards]').textContent();
      await useFace(page, 1);
      await press(result.getByRole('button', { name: words.retryStorage, exact: true }));
      await expect(result.getByRole('alert')).toHaveCount(0);
      await expect(result.locator('[data-rewards]')).toHaveText(reward!);
      expect(await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.inventory')!))).toEqual({
        special: { even: 0, odd: 0, devil: 2, weighted: 0 }, merchant: 2, firstWins: ['beggars'],
      });
    });
    test('unreadable inventory is retained until storage is corrected', async ({ page }) => {
      await page.evaluate(() => {
        localStorage.setItem('cogita.farkle.inventory', '{broken');
        localStorage.setItem('cogita.farkle.loadout', JSON.stringify({ normal: 5, even: 1, odd: 0, devil: 0, weighted: 0, merchant: 0 }));
      });
      await page.reload();
      await expect(page.getByRole('alert')).toContainText(words.inventoryLoadError);
      await menu(page, words.newGame);
      await expect(page.getByRole('button', { name: words.chooseDice, exact: true })).toBeDisabled();
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'))).toBe('{broken');
      await page.evaluate(() => localStorage.setItem('cogita.farkle.inventory', JSON.stringify({
        special: { even: 1, odd: 0, devil: 0, weighted: 0 }, merchant: 0, firstWins: [],
      })));
      await press(page.getByRole('button', { name: words.retryStorage, exact: true }));
      await expect(page.getByRole('alert')).toHaveCount(0);
      await expect(page.getByRole('button', { name: words.chooseDice, exact: true })).toBeEnabled();
      await press(page.getByRole('dialog').getByRole('button', { name: words.chooseDice, exact: true }));
      await expect(row(page, 'normal').locator('[data-selected-count]')).toHaveText('5');
      await expect(row(page, 'even').locator('[data-selected-count]')).toHaveText('1');
    });
    test('a full collection defeat shows only converted dice without a separator', async ({ page }) => {
      await page.evaluate(() => localStorage.setItem('cogita.farkle.inventory', JSON.stringify({
        special: { even: 6, odd: 6, devil: 6, weighted: 6 }, merchant: 0, firstWins: [],
      })));
      await page.reload();
      await start(page, 'masters');
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await settled(page);
      for (let index = 0; index < 6; index++) await press(die(page, `A${index}`));
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      const result = page.getByRole('dialog', { name: words.youLost, exact: true });
      await expect(result.locator('[data-reward-group]')).toHaveCount(1);
      await expect(result.locator('[data-reward-group="converted"] [data-reward-count]')).toHaveText(words.convertedAmount.replace('{{count}}', '1'));
      await expect(result.locator('[data-slot="separator"]')).toHaveCount(0);
      await expect(page.locator('[data-merchant-balance]')).toHaveText('1');
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
