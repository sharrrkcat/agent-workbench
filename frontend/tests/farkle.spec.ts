import { readFileSync } from 'node:fs';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { openSidebar } from './controls';
import { DICE_TYPES, SPECIAL_TYPES } from '../src/components/playground/farkle/dice';
import { newInventory, type Inventory } from '../src/components/playground/farkle/economy';
import { defaultLoadout } from '../src/components/playground/farkle/loadout';

type OpponentFrame = { at: number; player: string; phase: string; selected: string[]; hovered: string | null };
const fullSpecial = Object.fromEntries(SPECIAL_TYPES.map(({ id }) => [id, 6])) as Inventory['special'];
const englishOrder = ['aranka', 'ci', 'devil', 'misfortune', 'even', 'favourable', 'fer', 'grimy', 'heavenly', 'lu', 'lucky',
  'merchant', 'monk', 'normal', 'odd', 'painted', 'pie', 'shrinking', 'strip', 'unbalanced', 'unlucky', 'weighted'];
const stock = (special: Partial<Inventory['special']> = {}, merchant = 0, firstWins: Inventory['firstWins'] = []): Inventory =>
  ({ special: { ...newInventory().special, ...special }, merchant, firstWins });
const seedInventory = (page: Page, inventory: Inventory) => page.evaluate((value) =>
  localStorage.setItem('cogita.farkle.inventory', JSON.stringify(value)), inventory);

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
    async function nextOpponentFaces(page: Page, faces: number[]) {
      await page.evaluate(({ faces, definitions }) => {
        const fallback = Math.random;
        let index = 0;
        Math.random = () => {
          const board = document.querySelector('.farkle-table');
          if (index < faces.length && board?.getAttribute('data-player') === 'A' && board.getAttribute('data-phase') === 'view') {
            const type = document.querySelector(`[data-die-id="A${index}"]`)!.getAttribute('data-die-type');
            const weights = definitions.find((die) => die.id === type)!.weights;
            const face = faces[index++] - 1;
            return (weights.slice(0, face).reduce<number>((sum, weight) => sum + weight, 0) + weights[face] / 2)
              / weights.reduce<number>((sum, weight) => sum + weight, 0);
          }
          return fallback();
        };
      }, { faces, definitions: DICE_TYPES });
    }
    async function observeOpponent(page: Page) {
      await page.evaluate(() => {
        const frames: OpponentFrame[] = [];
        (window as typeof window & { farkleFrames: OpponentFrame[] }).farkleFrames = frames;
        const board = document.querySelector('.farkle-table')!;
        let previous = '';
        new MutationObserver(() => {
          const player = board.getAttribute('data-player')!;
          const phase = board.getAttribute('data-phase')!;
          if (player !== 'A' && phase !== 'view') return;
          const snapshot = {
            player, phase,
            selected: [...board.querySelectorAll('[data-state="selected"]')].map((node) => node.getAttribute('data-die-id')!),
            hovered: board.querySelector('[data-hovered="true"]')?.getAttribute('data-die-id') ?? null,
          };
          const key = JSON.stringify(snapshot);
          if (key !== previous) frames.push({ ...snapshot, at: performance.now() });
          previous = key;
        }).observe(board, { attributes: true, subtree: true, childList: true });
      });
    }
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
    async function start(page: Page, level = 'beggars', counts?: Record<string, number>, opponentSamples?: number[]) {
      await menu(page, words.newGame);
      const modal = page.getByRole('dialog', { name: words.newGame, exact: true });
      await press(modal.getByRole('button', { name: new RegExp(words.levels[level]) }));
      await press(modal.getByRole('button', { name: words.chooseDice, exact: true }));
      await choose(page, counts);
      await page.evaluate((samples) => {
        const fallback = Math.random;
        Math.random = () => samples.length ? samples.shift()! : fallback();
      }, opponentSamples ?? (level === 'beggars' || level === 'wagoners' ? [0] : [0, 0]));
      await press(choice(page).getByRole('button', { name: words.startGame, exact: true }));
      await expect(choice(page)).toBeHidden();
      await expect(page.locator('[data-die-id]')).toHaveCount(6);
      await settled(page);
    }
    test.beforeEach(async ({ page }) => {
      await page.addInitScript((value) => {
        localStorage.setItem('cogita.locale', value);
        Math.random = () => 0.7;
      }, locale);
      await page.goto('/playground/farkle');
    });
    test('baked throws stay visible and clear of the HUD in portrait and landscape', async ({ page }, testInfo) => {
      for (const viewport of [{ width, height: touch ? 844 : 900 }, { width: touch ? 667 : 844, height: 390 }]) {
        await page.setViewportSize(viewport);
        await expect(table(page)).toBeVisible();
        await page.evaluate(() => {
          const samples = { frames: 0, errors: [] as string[] };
          (window as typeof window & { rollSamples: typeof samples }).rollSamples = samples;
          const measure = () => {
            const board = document.querySelector('.farkle-table')!;
            if (board.getAttribute('data-phase') === 'roll') {
              samples.frames++;
              const area = board.getBoundingClientRect();
              const hud = [...board.querySelectorAll('.farkle-score, .farkle-actions')].map((node) => node.getBoundingClientRect());
              for (const die of board.querySelectorAll('[data-die-id][data-state="idle"]')) {
                const box = die.getBoundingClientRect();
                if (box.width <= 0) continue;
                const id = die.getAttribute('data-die-id');
                if (box.left < area.left || box.right > area.right || box.top < area.top || box.bottom > area.bottom)
                  samples.errors.push(`${id} leaves the table viewport`);
                if (hud.some((item) => box.left < item.right && box.right > item.left && box.top < item.bottom && box.bottom > item.top))
                  samples.errors.push(`${id} overlaps the HUD`);
              }
            }
            requestAnimationFrame(measure);
          };
          requestAnimationFrame(measure);
        });
        await useFace(page, 5);
        await start(page);
        await page.screenshot({ path: testInfo.outputPath(`baked-roll-${viewport.width}.png`) });
        const samples = await page.evaluate(() => (window as typeof window & { rollSamples: { frames: number; errors: string[] } }).rollSamples);
        expect(samples.frames).toBeGreaterThan(4);
        expect([...new Set(samples.errors)]).toEqual([]);
        await page.reload();
      }
    });
    test('choose six owned dice, keep drafts when going back, and persist only on start', async ({ page }, testInfo) => {
      await seedInventory(page, stock({ even: 1 }, 2));
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
      const saved = { ...defaultLoadout(), normal: 4, even: 1, merchant: 1 };
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
      expect(await choice(page).evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
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
        favourable: ['33.3%', '0.0%', '5.6%', '5.6%', '33.3%', '22.2%'],
        pie: ['46.2%', '7.7%', '23.1%', '23.1%', '0.0%', '0.0%'],
        painted: ['18.8%', '6.3%', '6.3%', '6.3%', '43.8%', '18.8%'],
        heavenly: ['36.8%', '10.5%', '10.5%', '10.5%', '10.5%', '21.1%'],
        grimy: ['6.3%', '31.3%', '6.3%', '6.3%', '43.8%', '6.3%'],
        aranka: ['28.6%', '4.8%', '28.6%', '4.8%', '28.6%', '4.8%'],
      })) {
        if (touch) {
          await page.getByRole('dialog').getByRole('heading').tap();
          await expect(page.locator('[data-dice-probabilities]')).toHaveCount(0);
          await press(inventoryRow(type).getByRole('button'));
        }
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
      await menu(page, words.myDice);
      await expect(notice).toHaveCount(0);
      await page.keyboard.press('Escape');
      await nextOpponentFaces(page, [3, 3, 3, 3, 5, 6]);
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await expect(notice).toHaveText(words.opponentTurn);
      await settled(page);
      await expect(table(page)).toHaveAttribute('data-view', 'A');
      await expect(notice).toHaveText(words.opponentTurn);
      await page.screenshot({ path: testInfo.outputPath('opponent-turn.png') });
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
      await expect(inventory.locator('li')).toHaveCount(22);
      await expect(inventory.locator('img')).toHaveCount(22);
      await expect(inventory.locator('[data-inventory-count]')).toHaveText(englishOrder.map((type) => type === 'normal' ? '×6' : type === 'merchant' ? '×0' : '0 / 6'));
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
      await expect(table(page)).toHaveAttribute('data-player', 'B');
      await expect(table(page)).toHaveAttribute('data-view', 'B');
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
    test('live scores, automatic opponent banking and passes with or without a selection', async ({ page }, testInfo) => {
      await start(page);
      await press(die(page, 'B0'));
      await expect(score(page, 'B', 'selected')).toHaveText('50');
      await expect(die(page, 'B0')).toHaveAttribute('aria-pressed', 'true');
      await press(page.getByRole('button', { name: words.scoreContinue, exact: true }));
      await settled(page);
      await expect(score(page, 'B', 'round')).toHaveText('50');
      await expect(score(page, 'B', 'selected')).toHaveText('0');
      await press(die(page, 'B1'));
      await nextOpponentFaces(page, [3, 3, 3, 3, 5, 6]);
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await settled(page);
      await expect(table(page)).toHaveAttribute('data-player', 'A');
      await expect(table(page)).toHaveAttribute('data-view', 'A');
      await expect(total(page, 'B')).toHaveText('100');
      await expect(score(page, 'B', 'round')).toHaveText('0');
      await expect(score(page, 'B', 'selected')).toHaveText('0');
      await expect(page.locator('[data-die-id]:enabled')).toHaveCount(0);
      await expect(page.locator('.farkle-actions button:enabled')).toHaveCount(0);
      await expect(score(page, 'A', 'selected')).toHaveText('650');
      await page.screenshot({ path: testInfo.outputPath('opponent-selected.png') });
      await expect(table(page)).toHaveAttribute('data-player', 'B');
      await settled(page);
      await expect(total(page, 'A')).toHaveText('650');
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
      await seedInventory(page, stock({ devil: 1 }));
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
      await expect(sidebar(page).locator('.sidebar-header [data-sidebar="menu-button"]')).toHaveText([words.newGame, words.myDice, words.shop]);
      await press(sidebar(page).getByRole('button', { name: words.newGame, exact: true }));
      await press(settings.getByRole('button', { name: words.chooseDice, exact: true }));
      await press(choice(page).getByRole('button', { name: words.startGame, exact: true }));
      await settled(page);
      await expect(total(page, 'B')).toHaveText('0');
      await expect(table(page)).toHaveAttribute('data-phase', 'idle');
    });
    test('opponent uses visible thinking, hover, selection and confirmation before winning', async ({ page }, testInfo) => {
      await start(page, 'masters');
      await observeOpponent(page);
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await settled(page);
      await expect(page.locator('[data-die-id]:enabled')).toHaveCount(0);
      await expect(page.locator('.farkle-actions button:enabled')).toHaveCount(0);
      for (const key of ['w', 'a', 's', 'd', 'e', 'f', 'q']) await page.keyboard.press(key);
      await die(page, 'A0').evaluate((node: HTMLButtonElement) => node.click());
      await expect(score(page, 'A', 'selected')).toHaveText('0');
      await expect(page.locator('.farkle-face-icon')).toBeVisible();
      await expect(score(page, 'A', 'selected')).toHaveText('4000');
      await page.screenshot({ path: testInfo.outputPath('ai-selected.png') });
      const result = page.getByRole('dialog', { name: words.youLost, exact: true });
      await expect(result).toBeVisible();
      const frames = await page.evaluate(() => (window as typeof window & { farkleFrames: OpponentFrame[] }).farkleFrames);
      const thinking = frames.find((frame) => frame.phase === 'idle')!;
      const firstHover = frames.find((frame) => frame.hovered)!;
      expect(firstHover.at - thinking.at).toBeGreaterThanOrEqual(1450);
      let prior = firstHover;
      for (let count = 1; count <= 6; count++) {
        const selected = frames.find((frame) => frame.phase === 'idle' && frame.selected.length === count)!;
        expect(selected.at - prior.at).toBeGreaterThanOrEqual(525);
        prior = selected;
      }
      expect(frames.find((frame) => frame.phase === 'store')!.at - prior.at).toBeGreaterThanOrEqual(850);
      await expect(result.getByRole('heading')).toHaveText(words.youLost);
      await expect(result.locator('[data-result-score="B"]')).toHaveText(words.resultScore.replace('{{score}}', '0'));
      await expect(result.locator('[data-result-score="A"]')).toHaveCount(0);
      await expect(result.locator('[data-slot="separator"]')).toHaveCount(0);
      await resultStyle(page, false);
      await page.screenshot({ path: testInfo.outputPath('loss.png') });
      const inventory = await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.inventory')!));
      expect(Object.values(inventory.special).reduce((sum: number, count) => sum + Number(count), 0)).toBe(1);
      const rewardType = SPECIAL_TYPES.find(({ id }) => inventory.special[id] === 1)!.id;
      expect(inventory.merchant).toBe(0);
      expect(inventory.firstWins).toEqual([]);
      await expect(table(page)).toHaveAttribute('data-view', 'A');
      await expect(table(page)).toHaveAttribute('data-phase', 'finished');
      await press(result.getByRole('button', { name: words.playAgain, exact: true }));
      await expect(choice(page)).toBeVisible();
      await expect(row(page, 'normal').locator('[data-selected-count]')).toHaveText('6');
      await expect(table(page)).toHaveAttribute('data-phase', 'finished');
      await adjust(page, 'normal', false);
      await adjust(page, rewardType, true);
      await press(choice(page).getByRole('button', { name: words.startGame, exact: true }));
      await settled(page);
      await expect(table(page)).toHaveAttribute('data-player', 'B');
      await expect(table(page)).toHaveAttribute('data-view', 'B');
      await expect(page.locator('[data-target-score]')).toHaveText('3000');
      await expect(total(page, 'A')).toHaveText('0');
      await expect(total(page, 'B')).toHaveText('0');
      await expect(page.locator('[data-state="idle"]')).toHaveCount(6);
      await expect(page.getByRole('dialog')).toHaveCount(0);
      await expect(page.locator(`[data-die-type="${rewardType}"]`)).toHaveCount(1);
      await expect(page.locator('[data-die-type="normal"]')).toHaveCount(5);
      expect(await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.inventory')!))).toEqual(inventory);
    });
    test('opponent pauses before handing banking and bust turns back to the player', async ({ page }) => {
      for (const { faces, banked } of [{ faces: [3, 3, 3, 3, 5, 6], banked: 650 }, { faces: [2, 2, 3, 3, 4, 6], banked: 0 }]) {
        await start(page);
        await nextOpponentFaces(page, faces);
        await observeOpponent(page);
        await press(page.getByRole('button', { name: words.pass, exact: true }));
        await expect(table(page)).toHaveAttribute('data-player', 'A');
        await expect(table(page)).toHaveAttribute('data-player', 'B');
        const frames = await page.evaluate(() => (window as typeof window & { farkleFrames: OpponentFrame[] }).farkleFrames);
        const pause = frames.find((frame) => frame.phase === 'turnEnd')!;
        expect(pause.player).toBe('A');
        expect(pause.selected).toEqual([]);
        expect(frames.find((frame) => frame.player === 'B' && frame.phase === 'view')!.at - pause.at).toBeGreaterThanOrEqual(475);
        if (!banked) expect(pause.at - frames.find((frame) => frame.phase === 'bust')!.at).toBeGreaterThanOrEqual(1150);
        await expect(total(page, 'A')).toHaveText(String(banked));
        await expect(score(page, 'A', 'round')).toHaveText('0');
        await settled(page);
      }
    });
    test('opponent pauses for overlays and background, and cancels old moves on restart and exit', async ({ page }) => {
      await start(page, 'masters');
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await settled(page);
      await menu(page, words.myDice);
      await expect(page.getByRole('dialog', { name: words.myDice, exact: true })).toBeVisible();
      await page.waitForTimeout(1800);
      await expect(score(page, 'A', 'selected')).toHaveText('0');
      await expect(total(page, 'A')).toHaveText('0');
      // Simulate losing visibility immediately after one real AI selection.
      await page.evaluate(() => {
        const board = document.querySelector('.farkle-table')!;
        const observer = new MutationObserver(() => {
          if (board.getAttribute('data-player') !== 'A' || !board.querySelector('[data-state="selected"]')) return;
          observer.disconnect();
          Object.defineProperty(document, 'hidden', { configurable: true, value: true });
          document.dispatchEvent(new Event('visibilitychange'));
        });
        observer.observe(board, { attributes: true, subtree: true });
      });
      await page.keyboard.press('Escape');
      await expect(page.locator('[data-state="selected"]')).toHaveCount(1);
      const hover = await page.locator('[data-hovered="true"]').getAttribute('data-die-id');
      await page.waitForTimeout(1000);
      for (const key of ['e', 'f', 'q']) await page.keyboard.press(key);
      await table(page).dispatchEvent('pointerdown', { pointerType: 'touch' });
      await expect(page.locator('[data-state="selected"]')).toHaveCount(1);
      await expect(page.locator('[data-hovered="true"]')).toHaveAttribute('data-die-id', hover!);
      await expect(page.locator('.farkle-face-icon')).toBeVisible();
      await expect(total(page, 'A')).toHaveText('0');
      await menu(page, words.newGame);
      await page.evaluate(() => {
        Reflect.deleteProperty(document, 'hidden');
        document.dispatchEvent(new Event('visibilitychange'));
      });
      await press(page.getByRole('dialog').getByRole('button', { name: words.chooseDice, exact: true }));
      await press(choice(page).getByRole('button', { name: words.startGame, exact: true }));
      await settled(page);
      await page.waitForTimeout(1000);
      await expect(table(page)).toHaveAttribute('data-player', 'B');
      await expect(page.locator('[data-state="selected"]')).toHaveCount(0);
      await expect(total(page, 'A')).toHaveText('0');
      await expect(total(page, 'B')).toHaveText('0');
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await settled(page);
      await menu(page, words.exitGame);
      await page.waitForTimeout(1800);
      await expect(page.locator('[data-die-id]')).toHaveCount(0);
      await expect(page.locator('[data-turn-notice]')).toHaveCount(0);
      await expect(page.getByRole('dialog')).toHaveCount(0);
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'))).toBeNull();
    });
    test('opponent calculation failure offers a retry of the current move', async ({ page }) => {
      await page.evaluate(() => {
        const NativeWorker = Worker;
        let fail = true;
        window.Worker = class extends NativeWorker {
          constructor(url: string | URL, options?: WorkerOptions) {
            super(url, options);
            if (String(url).includes('ai.worker')) {
              (window as typeof window & { farkleWorker: Worker }).farkleWorker = this;
              if (fail) {
                fail = false;
                queueMicrotask(() => this.dispatchEvent(new ErrorEvent('error', { message: 'Test worker failure' })));
              }
            }
          }
        };
      });
      await start(page, 'masters');
      await expect(page.getByRole('alert')).toHaveText(new RegExp(words.opponentError));
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await settled(page);
      await page.waitForTimeout(1700);
      await expect(score(page, 'A', 'selected')).toHaveText('0');
      await expect(total(page, 'A')).toHaveText('0');
      await press(page.getByRole('alert').getByRole('button', { name: words.retryOpponent, exact: true }));
      await expect(page.getByRole('alert')).toHaveCount(0);
      const result = page.getByRole('dialog', { name: words.youLost, exact: true });
      await expect(result).toBeVisible();

      await press(result.getByRole('button', { name: words.playAgain, exact: true }));
      await press(choice(page).getByRole('button', { name: words.startGame, exact: true }));
      await settled(page);
      await page.evaluate(() => {
        const board = document.querySelector('.farkle-table')!;
        const observer = new MutationObserver(() => {
          if (board.getAttribute('data-player') !== 'A' || !board.querySelector('[data-state="selected"]')) return;
          observer.disconnect();
          (window as typeof window & { farkleWorker: Worker }).farkleWorker
            .dispatchEvent(new ErrorEvent('error', { message: 'Test failure after selection' }));
        });
        observer.observe(board, { attributes: true, subtree: true });
      });
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await expect(page.getByRole('alert')).toHaveText(new RegExp(words.opponentError));
      await expect(page.locator('[data-state="selected"]')).toHaveCount(1);
      const retained = await page.locator('[data-state="selected"]').getAttribute('data-die-id');
      await press(page.getByRole('alert').getByRole('button', { name: words.retryOpponent, exact: true }));
      await expect(die(page, retained!)).toHaveAttribute('data-state', 'selected');
      await expect(result).toBeVisible();
      await expect(total(page, 'A')).toHaveText('4000');
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
      await page.evaluate((inventory) => localStorage.setItem('cogita.farkle.inventory', JSON.stringify({
        ...inventory, normal: 999, special: { ...inventory.special, normal: 999 },
      })), stock({ even: 1, odd: 1, devil: 1, weighted: 1 }, 1));
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
    test('chooser fits owned type count and sorts by English names in either locale', async ({ page }, testInfo) => {
      for (const count of [1, 6, 7, 12, 13]) {
        const specials = SPECIAL_TYPES.slice(0, count - 1);
        await seedInventory(page, stock(Object.fromEntries(specials.map(({ id }) => [id, 1]))));
        await page.reload();
        await menu(page, words.newGame);
        await press(page.getByRole('dialog').getByRole('button', { name: words.chooseDice, exact: true }));
        const maxWidth = count <= 6 ? 480 : count <= 12 ? 800 : 1200;
        const columns = touch || count <= 6 ? 1 : count <= 12 ? 2 : 3;
        await expect.poll(async () => (await choice(page).boundingBox())!.width).toBe(Math.min(width - 32, maxWidth));
        await expect.poll(() => choice(page).locator('.farkle-dice-grid').evaluate((node) => getComputedStyle(node).gridTemplateColumns.split(' ').length)).toBe(columns);
        expect(await choice(page).locator('[data-inventory-type]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-inventory-type'))))
          .toEqual(englishOrder.filter((type) => type === 'normal' || specials.some(({ id }) => id === type)));
        await adjust(page, 'normal', false);
        expect((await choice(page).boundingBox())!.width).toBe(Math.min(width - 32, maxWidth));
        await page.screenshot({ path: testInfo.outputPath(`chooser-${count}-types.png`) });
      }
    });
    test('expanded inventory and chooser use responsive columns and scroll below fixed controls', async ({ page }, testInfo) => {
      await seedInventory(page, stock(fullSpecial, 2));
      await page.reload();
      await menu(page, words.myDice);
      const modal = page.getByRole('dialog');
      const columns = () => modal.locator('.farkle-dice-grid').evaluate((node) => getComputedStyle(node).gridTemplateColumns.split(' ').length);
      await expect(modal.locator('[data-inventory-type]')).toHaveCount(22);
      expect(await modal.locator('[data-inventory-type]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-inventory-type')))).toEqual(englishOrder);
      for (const viewport of touch ? [{ width: 390, height: 844, columns: 1 }]
        : [{ width: 1366, height: 900, columns: 3 }, { width: 1024, height: 768, columns: 2 }, { width: 390, height: 844, columns: 1 }]) {
        await page.setViewportSize(viewport);
        await expect.poll(columns).toBe(viewport.columns);
        expect(await modal.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
        const bounds = (await modal.boundingBox())!;
        expect(bounds.x).toBeGreaterThanOrEqual(16);
        expect(bounds.x + bounds.width).toBeLessThanOrEqual(viewport.width - 16);
        await page.screenshot({ path: testInfo.outputPath(`catalog-${viewport.width}.png`) });
      }
      const thumbnail = modal.locator('[data-inventory-type="heavenly"] img');
      expect(await thumbnail.evaluate((node) => {
        const image = node as HTMLImageElement, canvas = document.createElement('canvas');
        canvas.width = canvas.height = 256;
        const context = canvas.getContext('2d')!; context.drawImage(image, 0, 0);
        return [context.getImageData(0, 0, 1, 1).data[3], context.getImageData(128, 128, 1, 1).data[3]];
      })).toEqual([0, 255]);
      await page.keyboard.press('Escape');
      await menu(page, words.newGame);
      await press(page.getByRole('dialog').getByRole('button', { name: words.chooseDice, exact: true }));
      await expect(choice(page).locator('[data-inventory-type]')).toHaveCount(22);
      expect(await choice(page).locator('[data-inventory-type]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-inventory-type')))).toEqual(englishOrder);
      await adjust(page, 'normal', false);
      await adjust(page, 'aranka', true);
      await expect(row(page, 'aranka').locator('[data-selected-count]')).toHaveText('1');
      await expect(choice(page).getByRole('button', { name: words.startGame, exact: true })).toBeEnabled();
      await page.setViewportSize({ width, height: 320 });
      await expect.poll(columns).toBe(touch ? 1 : 3);
      await expect.poll(() => choice(page).locator('.farkle-dice-list').evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true);
      await row(page, 'weighted').scrollIntoViewIfNeeded();
      for (const node of [choice(page).getByRole('heading'), choice(page).locator('[data-loadout-total]'),
        choice(page).getByRole('button', { name: words.startGame, exact: true })]) {
        const bounds = (await node.boundingBox())!;
        expect(bounds.y).toBeGreaterThanOrEqual(16);
        expect(bounds.y + bounds.height).toBeLessThanOrEqual(304);
      }
      await page.screenshot({ path: testInfo.outputPath('expanded-chooser-short.png') });
    });
    for (const [batch, types] of [
      ['lucky', 'unlucky', 'favourable', 'pie', 'misfortune', 'monk'],
      ['strip', 'unbalanced', 'shrinking', 'painted', 'heavenly', 'grimy'],
      ['normal', 'weighted', 'lu', 'ci', 'fer', 'aranka'],
    ].entries()) test(`new dice materials and persisted loadout batch ${batch + 1}`, async ({ page }, testInfo) => {
      const errors: string[] = []; page.on('pageerror', (error) => errors.push(error.message));
      await seedInventory(page, stock(fullSpecial));
      await page.reload();
      await useFace(page, 6);
      await start(page, 'courtiers', Object.fromEntries(types.map((type) => [type, 1])));
      await expect(page.locator('[data-die-id]')).toHaveCount(6);
      for (const [index, type] of types.entries()) {
        await expect(die(page, `B${index}`)).toHaveAttribute('data-die-type', type);
        if (!touch) {
          await die(page, `B${index}`).hover();
          if (type !== 'normal') await expect(page.locator('.farkle-die-name')).toHaveText(words.dice[type]);
        }
      }
      if (types.includes('heavenly')) {
        const heavenly = die(page, `B${types.indexOf('heavenly')}`);
        await expect(heavenly).toHaveAttribute('data-value', '6');
        await expect(heavenly).toHaveAccessibleName(new RegExp(words.faceValue.replace('{{value}}', '6')));
        if (!touch) {
          await heavenly.hover();
          await expect(page.locator('.farkle-face-icon .lucide-dice-6')).toBeVisible();
        }
        await press(heavenly);
        await expect(score(page, 'B', 'selected')).toHaveText('0');
        await expect(page.getByRole('button', { name: words.scoreContinue, exact: true })).toBeDisabled();
        await press(heavenly);
      }
      await page.screenshot({ path: testInfo.outputPath(`new-materials-${batch + 1}.png`) });
      await page.reload();
      await menu(page, words.newGame);
      await press(page.getByRole('dialog').getByRole('button', { name: words.chooseDice, exact: true }));
      for (const type of types) await expect(row(page, type).locator('[data-selected-count]')).toHaveText('1');
      expect(errors).toEqual([]);
    });
    test('opponent worker uses Heavenly and Pie dice with ordinary scoring', async ({ page }) => {
      const sample = (type: string) => (SPECIAL_TYPES.findIndex(({ id }) => id === type) + 0.5) / SPECIAL_TYPES.length;
      await start(page, 'courtiers', undefined, [0.99, sample('heavenly'), sample('pie')]);
      await nextOpponentFaces(page, [1, 1, 1, 1, 6, 1]);
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await settled(page);
      await expect(die(page, 'A4')).toHaveAttribute('data-die-type', 'heavenly');
      await expect(die(page, 'A5')).toHaveAttribute('data-die-type', 'pie');
      await expect(die(page, 'A4')).toHaveAttribute('data-value', '6');
      await expect(page.getByRole('dialog', { name: words.youLost, exact: true })).toBeVisible();
      await expect(total(page, 'A')).toHaveText('4000');
      await expect(die(page, 'A4')).toHaveAttribute('data-state', 'idle');
      await expect(die(page, 'A5')).toHaveAttribute('data-state', 'scored');
    });
    test('first win, overflow conversion, persistence and repeat win', async ({ page }, testInfo) => {
      await seedInventory(page, stock({ ...fullSpecial, even: 5, odd: 5 }));
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
      expect(JSON.parse(saved!)).toEqual(stock(fullSpecial, 5, ['courtiers']));
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
      await expect(result.locator('[data-reward-type="heavenly"]')).toContainText('+2');
      await expect(result.locator('[data-reward-group]')).toHaveCount(2);
      await expect(result.locator('[data-slot="separator"]')).toHaveCount(1);
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'))).toBeNull();
      const reward = await result.locator('[data-rewards]').textContent();
      await useFace(page, 1);
      await press(result.getByRole('button', { name: words.retryStorage, exact: true }));
      await expect(result.getByRole('alert')).toHaveCount(0);
      await expect(result.locator('[data-rewards]')).toHaveText(reward!);
      expect(await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.inventory')!))).toEqual(stock({ heavenly: 2 }, 2, ['beggars']));
    });
    test('unreadable inventory is retained until storage is corrected', async ({ page }) => {
      await page.evaluate((selection) => {
        localStorage.setItem('cogita.farkle.inventory', '{broken');
        localStorage.setItem('cogita.farkle.loadout', JSON.stringify(selection));
      }, { ...defaultLoadout(), normal: 5, even: 1 });
      await page.reload();
      await expect(page.getByRole('alert')).toContainText(words.inventoryLoadError);
      await menu(page, words.newGame);
      await expect(page.getByRole('button', { name: words.chooseDice, exact: true })).toBeDisabled();
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'))).toBe('{broken');
      await seedInventory(page, stock({ even: 1 }));
      await press(page.getByRole('button', { name: words.retryStorage, exact: true }));
      await expect(page.getByRole('alert')).toHaveCount(0);
      await expect(page.getByRole('button', { name: words.chooseDice, exact: true })).toBeEnabled();
      await press(page.getByRole('dialog').getByRole('button', { name: words.chooseDice, exact: true }));
      await expect(row(page, 'normal').locator('[data-selected-count]')).toHaveText('5');
      await expect(row(page, 'even').locator('[data-selected-count]')).toHaveText('1');
    });
    test('a full collection defeat shows only converted dice without a separator', async ({ page }) => {
      await seedInventory(page, stock(fullSpecial));
      await page.reload();
      await start(page, 'masters');
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
