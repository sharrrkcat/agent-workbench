import { readFileSync } from 'node:fs';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { openSidebar } from './controls';
import { DICE_TYPES, SPECIAL_TYPES } from '../src/components/playground/farkle/dice';
import { LEVELS, newInventory, type Inventory } from '../src/components/playground/farkle/economy';
import { defaultLoadout } from '../src/components/playground/farkle/loadout';

type OpponentFrame = { at: number; player: string; phase: string; selected: string[]; hovered: string | null };
const fullSpecial = Object.fromEntries(SPECIAL_TYPES.map(({ id }) => [id, 6])) as Inventory['special'];
const englishOrder = ['aranka', 'ci', 'devil', 'misfortune', 'even', 'favourable', 'fer', 'grimy', 'heavenly', 'lu', 'lucky',
  'merchant', 'monk', 'normal', 'odd', 'painted', 'pie', 'shrinking', 'strip', 'unbalanced', 'unlucky', 'weighted'];
const stock = (special: Partial<Inventory['special']> = {}, merchant = 0, firstWins: Inventory['firstWins'] = []): Inventory =>
  ({ special: { ...newInventory().special, ...special }, merchant, firstWins });
const seedInventory = (page: Page, inventory: Inventory) => page.evaluate((value) =>
  localStorage.setItem('cogita.farkle.inventory', JSON.stringify(value)), inventory);

async function expectCompactDiceLabels(list: Locator) {
  const rows = await list.locator('[data-inventory-type]').evaluateAll((nodes) => nodes.map((node) => {
    const name = document.createRange(), quantity = document.createRange();
    name.selectNodeContents(node.querySelector('[data-slot="hover-card-trigger"]')!);
    quantity.selectNodeContents(node.querySelector('[data-inventory-count]')!);
    return { type: node.getAttribute('data-inventory-type'),
      gap: quantity.getBoundingClientRect().top - name.getBoundingClientRect().bottom };
  }));
  for (const { type, gap } of rows) {
    expect(gap, `${type}: name to owned text`).toBeGreaterThanOrEqual(0);
    expect(gap, `${type}: name to owned text`).toBeLessThan(8);
  }
}

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
          if (type === 'normal') continue;
          const count = Number(await item.locator('[data-selected-count]').textContent());
          for (let index = 0; index < count; index++) await adjust(page, type, false);
        }
        for (const [type, count] of Object.entries(counts).filter(([type]) => type !== 'normal')) for (let index = 0; index < count; index++) await adjust(page, type, true);
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
        if (!localStorage.getItem('cogita.locale')) localStorage.setItem('cogita.locale', value);
        Math.random = () => 0.7;
      }, locale);
      await page.goto('/playground/farkle');
    });
    const dialog = (page: Page) => page.getByRole('dialog');
    const chosenCount = (page: Page, type: string) => dialog(page).locator(`[data-inventory-type="${type}"] [data-selected-count]`);
    const customAdjust = (page: Page, type: string, add: boolean) => press(dialog(page).getByRole('button', {
      name: (add ? words.addDie : words.removeDie).replace('{{name}}', words.dice[type]), exact: true,
    }));
    const nextPlayer = (page: Page) => press(dialog(page).getByRole('button', { name: words.choosePlayerDice, exact: true }));
    const nextOpponent = (page: Page) => press(dialog(page).getByRole('button', { name: words.chooseOpponentDice, exact: true }));
    const beginCustom = (page: Page) => press(dialog(page).getByRole('button', { name: words.startGame, exact: true }));

    test('custom opponent selection retains drafts, balances six and saves only confirmed settings', async ({ page }, testInfo) => {
      await menu(page, words.customGame);
      await expect(dialog(page).getByRole('heading')).toBeFocused();
      if (touch) await expect(sidebar(page)).toBeHidden();
      await dialog(page).getByLabel(words.targetScore, { exact: true }).fill('1501');
      await press(dialog(page).getByRole('button', { name: words.opponentModes.custom, exact: true }));
      const group = dialog(page).getByRole('group', { name: words.opponentDice, exact: true });
      await expect(group).toHaveAccessibleDescription(words.opponentModeHints.custom);
      await expect(group.locator('[aria-pressed="true"]')).toHaveCount(1);
      await expect.poll(async () => {
        const selected = (await group.locator('[aria-pressed="true"]').boundingBox())!;
        const indicator = (await group.locator('[data-slot="toggle-group-indicator"]').boundingBox())!;
        return Math.abs(selected.x - indicator.x) + Math.abs(selected.width - indicator.width);
      }).toBeLessThan(1);
      await page.screenshot({ path: testInfo.outputPath('custom-settings.png') });
      await nextOpponent(page);
      await expect(dialog(page)).toHaveAccessibleName(words.chooseOpponentDice);
      await expect(dialog(page).locator('[data-inventory-type]')).toHaveCount(22);
      await expect(dialog(page).locator('[data-inventory-count]')).toHaveCount(0);
      expect(await dialog(page).locator('[data-inventory-type]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-inventory-type')))).toEqual(englishOrder);
      for (let copy = 0; copy < 6; copy++) await customAdjust(page, 'weighted', true);
      await expect(chosenCount(page, 'normal')).toHaveText('0');
      await expect(dialog(page).getByRole('button', { name: words.addDie.replace('{{name}}', words.dice.weighted), exact: true })).toBeDisabled();
      await customAdjust(page, 'weighted', false);
      await customAdjust(page, 'merchant', true);
      await customAdjust(page, 'normal', true);
      await expect(chosenCount(page, 'merchant')).toHaveText('0');
      await expect(chosenCount(page, 'weighted')).toHaveText('5');
      await expect(chosenCount(page, 'normal')).toHaveText('1');
      await nextPlayer(page);
      await expect(dialog(page)).toHaveAccessibleName(words.choosePlayerDice);
      await expect(dialog(page).locator('[data-inventory-type]')).toHaveCount(22);
      await expect(dialog(page).locator('[data-inventory-count]')).toHaveCount(0);
      for (let copy = 0; copy < 6; copy++) await customAdjust(page, 'merchant', true);
      await expect(chosenCount(page, 'normal')).toHaveText('0');
      await expect(dialog(page).getByRole('button', { name: words.addDie.replace('{{name}}', words.dice.merchant), exact: true })).toBeDisabled();
      await press(dialog(page).getByRole('button', { name: common.back, exact: true }));
      await expect(chosenCount(page, 'weighted')).toHaveText('5');
      await press(dialog(page).getByRole('button', { name: common.back, exact: true }));
      await expect(dialog(page).getByLabel(words.targetScore, { exact: true })).toHaveValue('1501');
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.customGame'))).toBeNull();
      await nextOpponent(page);
      await page.screenshot({ path: testInfo.outputPath('custom-opponent.png') });
      await nextPlayer(page);
      await expect(chosenCount(page, 'merchant')).toHaveText('6');
      await beginCustom(page);
      await settled(page);
      await expect(page.locator('[data-target-score]')).toHaveText('1501');
      const config = await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.customGame')!));
      expect(config).toEqual({ target: 1501, opponentDiceMode: 'custom', opponentLoadout: { ...defaultLoadout(), normal: 1, weighted: 5 },
        playerLoadout: { ...defaultLoadout(), normal: 0, merchant: 6 } });
      expect(await page.locator('[data-die-id]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-die-type')))).toEqual(Array(6).fill('merchant'));
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.loadout'))).toBeNull();
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await expect(table(page)).toHaveAttribute('data-player', 'A');
      await settled(page);
      expect(await page.locator('[data-die-id]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-die-type'))))
        .toEqual(['normal', ...Array(5).fill('weighted')]);
      await menu(page, words.customGame);
      await dialog(page).getByLabel(words.targetScore, { exact: true }).fill('9000');
      await page.keyboard.press('Escape');
      if (touch) await expect(page.locator('[data-sidebar="trigger"]')).toBeFocused();
      else await expect(sidebar(page).getByRole('button', { name: words.customGame, exact: true })).toBeFocused();
      await page.reload();
      await menu(page, words.customGame);
      await expect(dialog(page).getByLabel(words.targetScore, { exact: true })).toHaveValue('1501');
      await nextOpponent(page);
      await expect(chosenCount(page, 'weighted')).toHaveText('5');
      await nextPlayer(page);
      await expect(chosenCount(page, 'merchant')).toHaveText('6');
    });

    test('standard and custom player choosers persist independent loadouts', async ({ page }) => {
      await seedInventory(page, stock({ even: 1 }, 2));
      await page.reload();
      await start(page, 'beggars', { even: 1 });
      await menu(page, words.customGame);
      await nextPlayer(page);
      await expect(chosenCount(page, 'even')).toHaveText('0');
      await customAdjust(page, 'merchant', true);
      await customAdjust(page, 'weighted', true);
      await press(dialog(page).getByRole('button', { name: common.back, exact: true }));
      await nextPlayer(page);
      await expect(chosenCount(page, 'merchant')).toHaveText('1');
      await expect(chosenCount(page, 'weighted')).toHaveText('1');
      await beginCustom(page);
      await settled(page);
      await menu(page, words.newGame);
      await press(dialog(page).getByRole('button', { name: words.chooseDice, exact: true }));
      await expect(chosenCount(page, 'normal')).toHaveText('5');
      await expect(chosenCount(page, 'even')).toHaveText('1');
      await expect(chosenCount(page, 'merchant')).toHaveText('0');
      await customAdjust(page, 'normal', true);
      await expect(chosenCount(page, 'even')).toHaveText('0');
      await beginCustom(page);
      await settled(page);
      await menu(page, words.customGame);
      await nextPlayer(page);
      await expect(chosenCount(page, 'normal')).toHaveText('4');
      await expect(chosenCount(page, 'merchant')).toHaveText('1');
      await expect(chosenCount(page, 'weighted')).toHaveText('1');
      await expect(chosenCount(page, 'even')).toHaveText('0');
      await customAdjust(page, 'weighted', false);
      await page.keyboard.press('Escape');
      await page.reload();
      await menu(page, words.customGame);
      await nextPlayer(page);
      await expect(chosenCount(page, 'weighted')).toHaveText('1');
      const stored = await page.evaluate(() => ({
        keys: Object.keys(localStorage).filter((key) => key.startsWith('cogita.farkle.')).sort(),
        config: JSON.parse(localStorage.getItem('cogita.farkle.customGame')!),
        standard: JSON.parse(localStorage.getItem('cogita.farkle.loadout')!),
      }));
      expect(stored.keys).toEqual(['cogita.farkle.customGame', 'cogita.farkle.inventory', 'cogita.farkle.loadout']);
      expect(Object.keys(stored.config).sort()).toEqual(['opponentDiceMode', 'opponentLoadout', 'playerLoadout', 'target']);
      expect(stored.standard).toEqual(defaultLoadout());
      expect(stored.config.playerLoadout).toEqual({ ...defaultLoadout(), normal: 4, weighted: 1, merchant: 1 });
    });

    test('custom generated opponent modes remain independent of standard Settings', async ({ page }) => {
      await menu(page, words.settings);
      await press(dialog(page).getByRole('button', { name: words.opponentModes.wild, exact: true }));
      await page.keyboard.press('Escape');
      for (const mode of ['dynamic', 'random', 'wild']) {
        await menu(page, words.customGame);
        await dialog(page).getByLabel(words.targetScore, { exact: true }).fill('1501');
        await press(dialog(page).getByRole('button', { name: words.opponentModes[mode], exact: true }));
        await expect(dialog(page).getByRole('group', { name: words.opponentDice, exact: true })).toHaveAccessibleDescription(words.opponentModeHints[mode]);
        await nextPlayer(page);
        const sample = mode === 'dynamic' ? 0 : 0.999;
        await page.evaluate((value) => { Math.random = () => value; }, sample);
        await beginCustom(page);
        await settled(page);
        expect(await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.settings')!)))
          .toEqual({ opponentDiceMode: 'wild' });
        await press(page.getByRole('button', { name: words.pass, exact: true }));
        await expect(table(page)).toHaveAttribute('data-player', 'A');
        await settled(page);
        const types = await page.locator('[data-die-id]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-die-type')));
        expect(types).toEqual(mode === 'dynamic' ? Array(6).fill('normal')
          : mode === 'random' ? [...Array(5).fill('normal'), 'aranka'] : Array(6).fill('merchant'));
        await menu(page, words.exitGame);
      }
      await page.reload();
      await menu(page, words.customGame);
      await expect(dialog(page).getByRole('button', { name: words.opponentModes.wild, exact: true })).toHaveAttribute('aria-pressed', 'true');
      await page.keyboard.press('Escape');
      await menu(page, words.settings);
      await expect(dialog(page).getByRole('button', { name: words.opponentModes.wild, exact: true })).toHaveAttribute('aria-pressed', 'true');
    });

    test('custom storage failures retain both drafts and retry only custom settings', async ({ page }) => {
      await menu(page, words.customGame);
      await dialog(page).getByLabel(words.targetScore, { exact: true }).fill('1501');
      await nextPlayer(page);
      await customAdjust(page, 'weighted', true);
      await page.evaluate(() => {
        const set = Storage.prototype.setItem;
        const get = Storage.prototype.getItem;
        let fail = true;
        Storage.prototype.getItem = function (key) {
          if (key === 'cogita.farkle.loadout') throw new DOMException('Standard storage blocked', 'SecurityError');
          return get.call(this, key);
        };
        Storage.prototype.setItem = function (key, value) {
          if (key === 'cogita.farkle.loadout') throw new DOMException('Standard storage blocked', 'SecurityError');
          if (key === 'cogita.farkle.customGame' && fail) { fail = false; throw new DOMException('Test quota', 'QuotaExceededError'); }
          set.call(this, key, value);
        };
      });
      await beginCustom(page);
      await expect(dialog(page).getByRole('alert')).toContainText(words.customSaveError);
      await expect(chosenCount(page, 'normal')).toHaveText('5');
      await expect(chosenCount(page, 'weighted')).toHaveText('1');
      await expect(page.locator('[data-die-id]')).toHaveCount(0);
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.customGame'))).toBeNull();
      await press(dialog(page).getByRole('button', { name: words.retryStorage, exact: true }));
      await settled(page);
      await expect(page.locator('[data-target-score]')).toHaveText('1501');
      await menu(page, words.customGame);
      await nextPlayer(page);
      await expect(chosenCount(page, 'weighted')).toHaveText('1');
    });

    test('custom read failure has an explicit retry and restores the stored configuration', async ({ page }) => {
      await page.evaluate((opponentLoadout) => {
        localStorage.setItem('cogita.farkle.customGame', JSON.stringify({ target: 10001, opponentDiceMode: 'random',
          opponentLoadout, playerLoadout: opponentLoadout }));
        const get = Storage.prototype.getItem;
        let fail = true;
        Storage.prototype.getItem = function (key) {
          if (key === 'cogita.farkle.customGame' && fail) { fail = false; throw new DOMException('Test access', 'SecurityError'); }
          return get.call(this, key);
        };
      }, defaultLoadout());
      await menu(page, words.customGame);
      await expect(dialog(page).getByRole('alert')).toContainText(words.customLoadError);
      await expect(dialog(page).getByRole('button', { name: words.choosePlayerDice, exact: true })).toBeDisabled();
      await press(dialog(page).getByRole('button', { name: words.retryStorage, exact: true }));
      await expect(dialog(page).getByLabel(words.targetScore, { exact: true })).toHaveValue('10001');
      await expect(dialog(page).getByRole('button', { name: words.opponentModes.random, exact: true })).toHaveAttribute('aria-pressed', 'true');
    });

    test('custom score validation accepts safe integers and the HUD displays the complete target', async ({ page }, testInfo) => {
      await menu(page, words.customGame);
      const field = dialog(page).getByLabel(words.targetScore, { exact: true });
      const next = dialog(page).getByRole('button', { name: words.choosePlayerDice, exact: true });
      for (const [invalid, reason] of [['', 'integer'], ['0', 'minimum'], ['1', 'minimum'], ['-1', 'minimum'],
        ['1.5', 'integer'], ['1e3', 'integer'], ['9007199254740991', 'maximum'], ['9007199254740992', 'maximum']]) {
        await field.fill(invalid);
        await expect(field).toHaveAttribute('aria-invalid', 'true');
        await expect(field).toHaveAccessibleDescription(words.targetErrors[reason]);
        await expect(dialog(page).getByRole('alert')).toHaveText(words.targetErrors[reason]);
        await expect(next).toBeDisabled();
      }
      for (const valid of ['2', '1501', '10000', '10001', '1000000000000', '9007199254740990']) {
        await field.fill(valid);
        await expect(field).toHaveAttribute('aria-invalid', 'false');
        await expect(next).toBeEnabled();
        await expect(field.locator('..')).not.toHaveAttribute('data-invalid');
      }
      await nextPlayer(page);
      await beginCustom(page);
      await settled(page);
      await expect(page.locator('[data-target-score]')).toHaveText('9007199254740990');
      const bounds = await page.locator('.farkle-hud').evaluate((hud) => {
        const score = hud.querySelector('.farkle-score')!, actions = hud.querySelector('.farkle-actions')!;
        return { scoreRight: score.getBoundingClientRect().right, actionsLeft: actions.getBoundingClientRect().left,
          overflow: [...score.querySelectorAll('div')].some((node) => node.scrollWidth > node.clientWidth + 1) };
      });
      expect(bounds.scoreRight).toBeLessThanOrEqual(bounds.actionsLeft);
      expect(bounds.overflow).toBe(false);
      if (!touch) {
        const heights = await page.locator('.farkle-score-heading').evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().height));
        expect(Math.max(...heights) - Math.min(...heights)).toBeLessThan(1);
      }
      await page.screenshot({ path: testInfo.outputPath('custom-large-target.png') });
    });

    for (const won of [true, false]) test(`custom ${won ? 'victory' : 'defeat'} has no rewards and replays its confirmed setup`, async ({ page }) => {
      await seedInventory(page, stock());
      await page.reload();
      const original = await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'));
      await menu(page, words.customGame);
      if (won) {
        await press(dialog(page).getByRole('button', { name: words.opponentModes.custom, exact: true }));
        await nextOpponent(page);
      }
      await nextPlayer(page);
      await customAdjust(page, 'merchant', true);
      await page.evaluate(() => { Math.random = () => 0; });
      await beginCustom(page);
      await settled(page);
      if (won) for (let i = 0; i < 6; i++) await press(die(page, `B${i}`));
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await expect(dialog(page)).toHaveAccessibleName(won ? words.youWin : words.youLost, { timeout: 15000 });
      await expect(dialog(page).locator('[data-rewards]')).toHaveCount(0);
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'))).toBe(original);
      await press(dialog(page).getByRole('button', { name: words.playAgain, exact: true }));
      await expect(dialog(page)).toHaveAccessibleName(won ? words.chooseOpponentDice : words.choosePlayerDice);
      if (won) await nextPlayer(page);
      await expect(chosenCount(page, 'merchant')).toHaveText('1');
      await beginCustom(page);
      await settled(page);
      for (let i = 0; i < 6; i++) await press(die(page, `B${i}`));
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await expect(dialog(page)).toHaveAccessibleName(words.youWin);
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'))).toBe(original);
      await press(dialog(page).getByRole('button', { name: words.newGame, exact: true }));
      await expect(dialog(page)).toHaveAccessibleName(words.newGame);
      await press(dialog(page).getByRole('button', { name: words.chooseDice, exact: true }));
      await beginCustom(page);
      await settled(page);
      for (let i = 0; i < 6; i++) await press(die(page, `B${i}`));
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await expect(dialog(page)).toHaveAccessibleName(words.youWin);
      await expect(dialog(page).locator('[data-rewards]')).toBeVisible();
      const inventory = await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.inventory')!));
      expect(inventory.firstWins).toEqual(['beggars']);
      expect(inventory.merchant).toBe(2);
    });
    test('settings language switches the shared UI, persists and retains the match', async ({ page }) => {
      const nextLocale = locale === 'en' ? 'zh-CN' : 'en';
      const translated = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${nextLocale}/common.json`, import.meta.url), 'utf8'));
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      await start(page);
      const diceBefore = await table(page).locator('[data-die-id]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-die-type')));
      await menu(page, words.settings);
      const language = dialog(page).getByRole('group', { name: common.language, exact: true });
      await language.getByRole('button', { name: locale === 'en' ? 'English' : '简体中文', exact: true }).focus();
      await page.keyboard.press(locale === 'en' ? 'ArrowRight' : 'ArrowLeft');
      await page.keyboard.press('Space');
      await expect(dialog(page).getByRole('heading')).toHaveText(translated.farkle.settings);
      await expect(dialog(page).getByRole('group', { name: translated.language, exact: true }).locator('[aria-pressed="true"]')).toHaveCount(1);
      await expect(dialog(page).getByRole('button', { name: translated.farkle.fillDice, exact: true })).toBeVisible();
      expect(await page.evaluate(() => localStorage.getItem('cogita.locale'))).toBe(nextLocale);
      await press(dialog(page).getByRole('button', { name: translated.close, exact: true }));
      await expect(table(page)).toHaveAttribute('data-phase', 'idle');
      expect(await table(page).locator('[data-die-id]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-die-type')))).toEqual(diceBefore);
      await page.reload();
      await menu(page, translated.farkle.settings);
      await expect(dialog(page).getByRole('button', { name: nextLocale === 'en' ? 'English' : '简体中文', exact: true })).toHaveAttribute('aria-pressed', 'true');
      expect(errors).toEqual([]);
    });
    test('settings language reports a failed preference write and retries', async ({ page }) => {
      const nextLocale = locale === 'en' ? 'zh-CN' : 'en';
      const translated = JSON.parse(readFileSync(new URL(`../src/i18n/resources/${nextLocale}/common.json`, import.meta.url), 'utf8'));
      await menu(page, words.settings);
      await page.evaluate(() => {
        const original = Storage.prototype.setItem;
        let fail = true;
        Storage.prototype.setItem = function (key, value) {
          if (key === 'cogita.locale' && fail) { fail = false; throw new DOMException('Test quota', 'QuotaExceededError'); }
          original.call(this, key, value);
        };
      });
      await press(dialog(page).getByRole('button', { name: nextLocale === 'en' ? 'English' : '简体中文', exact: true }));
      await expect(dialog(page).getByRole('alert')).toHaveText(new RegExp(translated.farkle.languageSaveError));
      expect(await page.evaluate(() => localStorage.getItem('cogita.locale'))).toBe(locale);
      await press(dialog(page).getByRole('button', { name: translated.farkle.retryStorage, exact: true }));
      await expect(dialog(page).getByRole('alert')).toHaveCount(0);
      await page.reload();
      await menu(page, translated.farkle.settings);
      await expect(dialog(page).getByRole('button', { name: nextLocale === 'en' ? 'English' : '简体中文', exact: true })).toHaveAttribute('aria-pressed', 'true');
    });
    test('inventory maintenance preserves first wins and current dice, and revalidates the next loadout', async ({ page }, testInfo) => {
      const firstWins: Inventory['firstWins'] = ['beggars', 'electors'];
      await seedInventory(page, stock({ even: 2 }, 2000, firstWins));
      await page.reload();
      await start(page, 'beggars', { even: 2, merchant: 1 });
      const diceBefore = await table(page).locator('[data-die-id]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-die-type')));
      const savedLoadout = await page.evaluate(() => localStorage.getItem('cogita.farkle.loadout'));
      await menu(page, words.settings);
      const actions = dialog(page).locator('[data-inventory-actions]');
      await expect(actions.getByRole('button')).toHaveText([words.fillDice, words.clearDice, words.addMerchantDice, words.clearMerchantDice]);
      await expect(actions.locator('[data-slot="field-description"]')).toHaveCount(0);
      const action = (key: string) => press(actions.getByRole('button', { name: words[key], exact: true }));
      const storedInventory = () => page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.inventory')!));
      await action('fillDice');
      expect(await storedInventory()).toEqual(stock(fullSpecial, 999, firstWins));
      await action('addMerchantDice'); await action('addMerchantDice');
      await expect(page.locator('[data-merchant-balance]')).toHaveText('2997');
      await action('clearMerchantDice');
      expect(await storedInventory()).toEqual(stock(fullSpecial, 0, firstWins));
      await action('clearDice');
      expect(await storedInventory()).toEqual(stock({}, 0, firstWins));
      const positions = await actions.getByRole('button').evaluateAll((nodes) => nodes.map((node) => {
        const box = node.getBoundingClientRect(); return { x: box.x, y: box.y, height: box.height };
      }));
      expect(positions[0].y === positions[1].y).toBe(!touch);
      if (touch) for (const { height } of positions) expect(height).toBeGreaterThanOrEqual(44);
      await expect(dialog(page).getByRole('button', { name: words.clearCache, exact: true })).toHaveAccessibleDescription(words.clearCacheHint);
      await page.screenshot({ path: testInfo.outputPath('inventory-settings.png') });
      await page.keyboard.press('Escape');
      expect(await table(page).locator('[data-die-id]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-die-type')))).toEqual(diceBefore);
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.loadout'))).toBe(savedLoadout);
      await menu(page, words.newGame);
      await press(dialog(page).getByRole('button', { name: words.chooseDice, exact: true }));
      await expect(row(page, 'normal').locator('[data-selected-count]')).toHaveText('6');
      await expect(choice(page).locator('[data-inventory-type]')).toHaveCount(1);
      await page.reload();
      await menu(page, words.myDice);
      await expect(dialog(page).locator('[data-inventory-type="normal"] [data-inventory-count]')).toHaveText('6 / 6');
      expect(await storedInventory()).toEqual(stock({}, 0, firstWins));
    });
    test('inventory maintenance retries one fixed addition and enforces safe integer bounds', async ({ page }) => {
      await seedInventory(page, stock({}, 7, ['electors']));
      await page.reload();
      await menu(page, words.settings);
      await page.evaluate(() => {
        const original = Storage.prototype.setItem;
        let fail = true;
        Storage.prototype.setItem = function (key, value) {
          if (key === 'cogita.farkle.inventory' && fail) { fail = false; throw new DOMException('Test quota', 'QuotaExceededError'); }
          original.call(this, key, value);
        };
      });
      await press(dialog(page).getByRole('button', { name: words.addMerchantDice, exact: true }));
      await expect(dialog(page).getByRole('alert')).toContainText(words.inventorySaveError);
      await expect(page.locator('[data-merchant-balance]')).toHaveText('1006');
      expect(await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.inventory')!).merchant)).toBe(7);
      for (const button of await dialog(page).locator('[data-inventory-actions] button').all()) await expect(button).toBeDisabled();
      await page.keyboard.press('Escape');
      await menu(page, words.settings);
      await press(dialog(page).getByRole('button', { name: words.retryStorage, exact: true }));
      expect(await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.inventory')!))).toEqual(stock({}, 1006, ['electors']));
      await press(dialog(page).getByRole('button', { name: words.addMerchantDice, exact: true }));
      await expect(page.locator('[data-merchant-balance]')).toHaveText('2005');
      await seedInventory(page, stock({}, Number.MAX_SAFE_INTEGER - 999));
      await page.reload();
      await menu(page, words.settings);
      await press(dialog(page).getByRole('button', { name: words.addMerchantDice, exact: true }));
      expect(await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.inventory')!).merchant)).toBe(Number.MAX_SAFE_INTEGER);
      await expect(dialog(page).getByRole('button', { name: words.addMerchantDice, exact: true })).toBeDisabled();
      await expect(dialog(page).getByRole('button', { name: words.fillDice, exact: true })).toBeEnabled();
    });
    test('cache reset repairs unreadable records and retries partial removal without touching other preferences', async ({ page }) => {
      await page.evaluate(() => {
        for (const key of ['inventory', 'loadout', 'settings', 'customGame']) localStorage.setItem(`cogita.farkle.${key}`, '{broken');
        localStorage.setItem('unrelated.preference', 'retained');
      });
      await page.reload();
      await menu(page, words.settings);
      await expect(dialog(page).getByRole('alert')).toContainText(words.inventoryLoadError);
      for (const button of await dialog(page).locator('[data-inventory-actions] button').all()) await expect(button).toBeDisabled();
      await page.evaluate(() => {
        const original = Storage.prototype.removeItem;
        let fail = true;
        Storage.prototype.removeItem = function (key) {
          if (key === 'cogita.farkle.settings' && fail) { fail = false; throw new DOMException('Storage denied', 'SecurityError'); }
          original.call(this, key);
        };
      });
      await press(dialog(page).getByRole('button', { name: words.clearCache, exact: true }));
      await expect(dialog(page)).toBeVisible();
      const error = dialog(page).getByRole('alert').filter({ hasText: words.clearCacheError });
      await expect(error).toBeVisible();
      await press(error.getByRole('button', { name: words.retryStorage, exact: true }));
      await expect(dialog(page)).toHaveCount(0);
      await expect(page.locator('[data-merchant-balance]')).toHaveText('0');
      await expect(page.getByRole('alert')).toHaveCount(0);
      expect(await page.evaluate(() => Object.keys(localStorage).filter((key) => key.startsWith('cogita.farkle.')))).toEqual([]);
      expect(await page.evaluate(() => localStorage.getItem('cogita.locale'))).toBe(locale);
      expect(await page.evaluate(() => localStorage.getItem('unrelated.preference'))).toBe('retained');
      await expect(touch ? page.locator('[data-sidebar="trigger"]') : sidebar(page).getByRole('button', { name: words.settings, exact: true })).toBeFocused();
      await menu(page, words.customGame);
      await expect(dialog(page).getByRole('textbox')).toHaveValue('1500');
      await expect(dialog(page).getByRole('button', { name: words.opponentModes.dynamic, exact: true })).toHaveAttribute('aria-pressed', 'true');
      await page.keyboard.press('Escape');
      await start(page);
      await expect(table(page)).toHaveAttribute('data-phase', 'idle');
    });
    test('cache reset discards pending rewards and pending settings without resurrecting records', async ({ page }) => {
      await page.evaluate(() => {
        const original = Storage.prototype.setItem;
        const failed = new Set<string>();
        Storage.prototype.setItem = function (key, value) {
          if (['cogita.farkle.inventory', 'cogita.farkle.settings'].includes(key) && !failed.has(key)) {
            failed.add(key); throw new DOMException('Test quota', 'QuotaExceededError');
          }
          original.call(this, key, value);
        };
      });
      await start(page);
      for (let index = 0; index < 5; index++) await press(die(page, `B${index}`));
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await expect(dialog(page).getByRole('alert')).toContainText(words.inventorySaveError);
      await page.keyboard.press('Escape');
      await menu(page, words.settings);
      await press(dialog(page).getByRole('button', { name: words.opponentModes.wild, exact: true }));
      await expect(dialog(page).getByRole('alert').filter({ hasText: words.settingsSaveError })).toBeVisible();
      await press(dialog(page).getByRole('button', { name: words.clearCache, exact: true }));
      await expect(table(page).locator('[data-die-id]')).toHaveCount(0);
      await menu(page, words.settings);
      await expect(dialog(page).getByRole('alert')).toHaveCount(0);
      await expect(dialog(page).getByRole('button', { name: words.opponentModes.dynamic, exact: true })).toHaveAttribute('aria-pressed', 'true');
      expect(await page.evaluate(() => Object.keys(localStorage).filter((key) => key.startsWith('cogita.farkle.')))).toEqual([]);
      await page.keyboard.press('Escape');
      await start(page);
      for (let index = 0; index < 5; index++) await press(die(page, `B${index}`));
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await expect(dialog(page).locator('[data-reward-group="firstWin"]')).toBeVisible();
      expect(await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.inventory')!))).toEqual(stock({ heavenly: 2 }, 2, ['beggars']));
    });
    test('cache reset cancels an active opponent and restores an empty table', async ({ page }) => {
      await page.evaluate(() => {
        const terminate = Worker.prototype.terminate;
        Object.defineProperty(window, 'farkleTerminations', { value: 0, writable: true });
        Worker.prototype.terminate = function () {
          (window as typeof window & { farkleTerminations: number }).farkleTerminations++;
          terminate.call(this);
        };
      });
      await start(page);
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      await expect(table(page)).toHaveAttribute('data-player', 'A');
      await menu(page, words.settings);
      await press(dialog(page).getByRole('button', { name: words.clearCache, exact: true }));
      await expect(table(page).locator('[data-die-id]')).toHaveCount(0);
      await expect(page.locator('[data-turn-notice]')).toHaveCount(0);
      await expect.poll(() => page.evaluate(() => (window as typeof window & { farkleTerminations: number }).farkleTerminations)).toBe(1);
      await start(page);
      await expect(table(page)).toHaveAttribute('data-player', 'B');
      await expect(total(page, 'B')).toHaveText('0');
    });
    test('settings and ten-level selection scroll on short screens with fixed headings and progression', async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: 430 });
      await menu(page, words.settings);
      const body = dialog(page).locator('[data-slot="field-group"]');
      expect(await body.evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true);
      await dialog(page).getByRole('button', { name: words.clearCache, exact: true }).scrollIntoViewIfNeeded();
      await expect(dialog(page).getByRole('heading')).toBeInViewport();
      await expect(dialog(page).getByRole('button', { name: words.clearCache, exact: true })).toBeInViewport();
      await page.screenshot({ path: testInfo.outputPath('settings-short.png') });
      await page.keyboard.press('Escape');
      await menu(page, words.newGame);
      const levels = dialog(page).getByRole('group', { name: words.level, exact: true });
      await expect(levels.getByRole('button')).toHaveCount(10);
      await press(levels.getByRole('button', { name: new RegExp(words.levels.electors) }));
      await expect(dialog(page).getByRole('heading')).toBeInViewport();
      const proceed = dialog(page).getByRole('button', { name: words.chooseDice, exact: true });
      await expect(proceed).toBeInViewport();
      expect(await levels.evaluate((node) => node.scrollHeight > node.clientHeight && node.scrollTop > 0)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath('levels-short.png') });
      await press(proceed);
      await press(choice(page).getByRole('button', { name: words.startGame, exact: true }));
      await expect(page.locator('[data-target-score]')).toHaveText('10000');
    });
    test('new level wins settle separate first rewards and replay the same target', async ({ page }) => {
      await useFace(page, 1);
      await start(page, 'electors');
      for (let index = 0; index < 6; index++) await press(die(page, `B${index}`));
      await press(page.getByRole('button', { name: words.scoreContinue, exact: true }));
      await settled(page);
      for (let index = 0; index < 6; index++) await press(die(page, `B${index}`));
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      const result = dialog(page);
      await expect(result.getByRole('heading')).toHaveText(words.youWin);
      await expect(result.locator('[data-reward-group="regular"] [data-reward-type="merchant"]')).toContainText('+4');
      await expect(result.locator('[data-reward-group="firstWin"]')).toContainText(words.firstWinAmount.replace('{{count}}', '4'));
      const inventory = await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.inventory')!));
      expect(inventory.merchant).toBe(8);
      expect(inventory.firstWins).toEqual(['electors']);
      expect(Object.values(inventory.special).reduce((sum: number, count) => sum + Number(count), 0)).toBe(4);
      await press(result.getByRole('button', { name: words.playAgain, exact: true }));
      await press(choice(page).getByRole('button', { name: words.startGame, exact: true }));
      await expect(page.locator('[data-target-score]')).toHaveText('10000');
      await expect(total(page, 'B')).toHaveText('0');
    });
    test('opponent settings slide, stay single-select and persist in both input layouts', async ({ page }, testInfo) => {
      await menu(page, words.settings);
      const modal = page.getByRole('dialog', { name: words.settings, exact: true });
      const group = modal.getByRole('group', { name: words.opponentDice, exact: true });
      const mode = (value: string) => group.getByRole('button', { name: words.opponentModes[value], exact: true });
      await expect(modal.getByRole('heading')).toBeFocused();
      await expect(mode('dynamic')).toHaveAttribute('aria-pressed', 'true');
      await expect(group).toHaveAccessibleDescription(words.opponentModeHints.dynamic);
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.settings'))).toBeNull();
      if (touch) await expect(sidebar(page)).toBeHidden();
      await press(mode('dynamic'));
      await expect(group.locator('[aria-pressed="true"]')).toHaveCount(1);
      await mode('dynamic').focus();
      await page.keyboard.press('ArrowRight');
      await expect(mode('random')).toBeFocused();
      await page.keyboard.press('Space');
      await expect(mode('random')).toHaveAttribute('aria-pressed', 'true');
      await expect(group).toHaveAccessibleDescription(words.opponentModeHints.random);
      await expect(group.locator('[aria-pressed="true"]')).toHaveCount(1);
      await press(mode('wild'));
      await expect(mode('wild')).toHaveAttribute('aria-pressed', 'true');
      await expect(group).toHaveAccessibleDescription(words.opponentModeHints.wild);
      const indicator = group.locator('[data-slot="toggle-group-indicator"]');
      await expect.poll(async () => {
        const selected = (await mode('wild').boundingBox())!, highlight = (await indicator.boundingBox())!;
        return Math.abs(selected.x - highlight.x) + Math.abs(selected.width - highlight.width);
      }).toBeLessThan(1);
      for (const button of await group.getByRole('button').all()) {
        const box = (await button.boundingBox())!;
        if (touch) expect(box.height).toBeGreaterThanOrEqual(44);
        expect(box.x).toBeGreaterThanOrEqual(16);
        expect(box.x + box.width).toBeLessThanOrEqual(width - 16);
      }
      expect(await modal.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath('opponent-settings.png') });
      await page.emulateMedia({ reducedMotion: 'reduce' });
      await expect(indicator).toHaveCSS('transition-property', 'none');
      expect(await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.settings')!))).toEqual({ opponentDiceMode: 'wild' });
      await page.keyboard.press('Escape');
      await expect(touch ? page.locator('[data-sidebar="trigger"]') : sidebar(page).getByRole('button', { name: words.settings, exact: true })).toBeFocused();
      await page.reload();
      await menu(page, words.settings);
      await expect(mode('wild')).toHaveAttribute('aria-pressed', 'true');
      await modal.getByRole('button', { name: common.close, exact: true }).click();
      await expect(modal).toBeHidden();
    });
    test('opponent settings report storage failures and retry without applying unsaved choices', async ({ page }) => {
      await menu(page, words.settings);
      const modal = page.getByRole('dialog', { name: words.settings, exact: true });
      const mode = (value: string) => modal.getByRole('button', { name: words.opponentModes[value], exact: true });
      await page.evaluate(() => {
        const original = Storage.prototype.setItem;
        Object.defineProperty(window, 'farkleSettingsWriteBlocked', { configurable: true, writable: true, value: true });
        Storage.prototype.setItem = function (key, value) {
          if (key === 'cogita.farkle.settings' && (window as typeof window & { farkleSettingsWriteBlocked: boolean }).farkleSettingsWriteBlocked)
            throw new DOMException('Storage denied', 'QuotaExceededError');
          original.call(this, key, value);
        };
      });
      await press(mode('wild'));
      await expect(modal.getByText(words.settingsSaveError, { exact: true })).toBeVisible();
      await expect(mode('dynamic')).toHaveAttribute('aria-pressed', 'true');
      await expect(mode('wild')).toHaveAttribute('aria-pressed', 'false');
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.settings'))).toBeNull();
      await page.keyboard.press('Escape');
      await menu(page, words.settings);
      await expect(modal.getByText(words.settingsSaveError, { exact: true })).toBeVisible();
      await page.evaluate(() => { (window as typeof window & { farkleSettingsWriteBlocked: boolean }).farkleSettingsWriteBlocked = false; });
      await press(modal.getByRole('button', { name: words.retryStorage, exact: true }));
      await expect(mode('wild')).toHaveAttribute('aria-pressed', 'true');
      await expect(modal.getByRole('alert')).toHaveCount(0);
      await page.addInitScript(() => {
        const original = Storage.prototype.getItem;
        Object.defineProperty(window, 'farkleSettingsReadBlocked', { configurable: true, writable: true, value: true });
        Storage.prototype.getItem = function (key) {
          if (key === 'cogita.farkle.settings' && (window as typeof window & { farkleSettingsReadBlocked: boolean }).farkleSettingsReadBlocked)
            throw new DOMException('Storage denied', 'SecurityError');
          return original.call(this, key);
        };
      });
      await page.reload();
      await menu(page, words.settings);
      await expect(modal.getByText(words.settingsLoadError, { exact: true })).toBeVisible();
      await expect(mode('dynamic')).toBeDisabled();
      await expect(mode('dynamic')).toHaveAttribute('aria-pressed', 'true');
      await page.evaluate(() => { (window as typeof window & { farkleSettingsReadBlocked: boolean }).farkleSettingsReadBlocked = false; });
      await press(modal.getByRole('button', { name: words.retryStorage, exact: true }));
      await expect(mode('wild')).toHaveAttribute('aria-pressed', 'true');
      await expect(mode('wild')).toBeEnabled();
      await expect(modal.getByRole('alert')).toHaveCount(0);
    });
    test('opponent settings apply only to the next confirmed new game or replay', async ({ page }) => {
      await page.evaluate(() => {
        const loadouts: string[][] = [];
        Object.defineProperty(window, 'farklePreparedLoadouts', { configurable: true, value: loadouts });
        const Original = window.Worker;
        window.Worker = class extends Original {
          postMessage(message: { kind: string; types?: string[] }) {
            if (message.kind === 'prepare') loadouts.push([...message.types!]);
            super.postMessage(message);
          }
        };
      });
      const prepared = () => page.evaluate(() => (window as typeof window & { farklePreparedLoadouts: string[][] }).farklePreparedLoadouts);
      await start(page, 'masters', undefined, [0.75, 0]);
      const original = await prepared();
      expect(original).toHaveLength(1);
      expect(original[0].filter((type) => type !== 'normal')).toHaveLength(2);
      await menu(page, words.settings);
      let modal = page.getByRole('dialog', { name: words.settings, exact: true });
      await press(modal.getByRole('button', { name: words.opponentModes.random, exact: true }));
      await page.keyboard.press('Escape');
      expect(await prepared()).toEqual(original);
      await start(page, 'masters', undefined, [0.75, 0, 0]);
      expect(await prepared()).toEqual([...original, ['normal', 'normal', 'normal', 'normal', 'even', 'even']]);
      await menu(page, words.settings);
      modal = page.getByRole('dialog', { name: words.settings, exact: true });
      await press(modal.getByRole('button', { name: words.opponentModes.wild, exact: true }));
      await page.keyboard.press('Escape');
      expect(await prepared()).toHaveLength(2);
      for (let index = 0; index < 6; index++) await press(die(page, `B${index}`));
      await press(page.getByRole('button', { name: words.pass, exact: true }));
      const result = page.getByRole('dialog', { name: words.youWin, exact: true });
      await expect(result).toBeVisible();
      await press(result.getByRole('button', { name: words.playAgain, exact: true }));
      expect(await prepared()).toHaveLength(2);
      await page.evaluate(() => {
        const previous = Math.random; let remaining = 6;
        Math.random = () => remaining-- > 0 ? 4.5 / 22 : previous();
      });
      await press(choice(page).getByRole('button', { name: words.startGame, exact: true }));
      await settled(page);
      expect(await prepared()).toHaveLength(3);
      expect((await prepared())[2]).toEqual(Array(6).fill('weighted'));
      await expect(page.locator('[data-target-score]')).toHaveText('3000');
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
      await expect(row(page, 'normal').locator('[data-inventory-count]')).toHaveText(words.owned.replace('{{count}}', '6'));
      await expect(row(page, 'even').locator('[data-inventory-count]')).toHaveText(words.owned.replace('{{count}}', '1'));
      await expect(row(page, 'normal').locator('[data-selected-count]')).toHaveText('6');
      await expect(row(page, 'normal')).toHaveAttribute('data-loadout-count', '6');
      await expect(row(page, 'even')).toHaveAttribute('data-loadout-count', '0');
      const addEven = row(page, 'even').getByRole('button', { name: words.addDie.replace('{{name}}', words.dice.even), exact: true });
      await expect(addEven).toBeEnabled();
      await expect(row(page, 'normal').getByRole('button', { name: words.removeDie.replace('{{name}}', words.dice.normal), exact: true })).toBeDisabled();
      await expect(choice(page).getByRole('button', { name: words.startGame, exact: true })).toBeEnabled();
      await adjust(page, 'even', true);
      await expect(row(page, 'even')).toHaveAttribute('data-loadout-count', '1');
      const selectedStyle = await row(page, 'even').evaluate((node) => {
        const selected = getComputedStyle(node), unselected = getComputedStyle(document.querySelector('[data-loadout-count="0"]')!);
        return { selected: [selected.borderColor, selected.backgroundColor], unselected: [unselected.borderColor, unselected.backgroundColor] };
      });
      expect(selectedStyle.selected[0]).not.toEqual(selectedStyle.unselected[0]);
      expect(selectedStyle.selected[1]).not.toEqual(selectedStyle.unselected[1]);
      await adjust(page, 'even', false);
      await expect(row(page, 'even')).toHaveAttribute('data-loadout-count', '0');
      await adjust(page, 'even', true);
      await expect(addEven).toBeDisabled();
      await adjust(page, 'merchant', true);
      await expect(choice(page).locator('[data-loadout-total]')).toHaveCount(0);
      await expect(row(page, 'normal').locator('[data-selected-count]')).toHaveText('4');
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
      await adjust(page, 'normal', true);
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
      const quantity = row(page, 'normal').locator('[data-inventory-count]');
      if (touch) await quantity.tap(); else await quantity.hover();
      await expect(page.locator('[data-dice-probabilities]')).toHaveCount(0);
      if (touch) await press(name); else await name.hover();
      await expect(page.locator('[data-dice-probabilities="normal"]')).toBeVisible();
      await expect(row(page, 'normal').getByRole('button', { name: words.removeDie.replace('{{name}}', words.dice.normal), exact: true })).toBeDisabled();
      await expect(row(page, 'normal').locator('[data-selected-count]')).toHaveText('6');
      const positions = await row(page, 'normal').evaluate((node) => {
        const name = node.querySelector('[data-slot="hover-card-trigger"]')!;
        const quantity = node.querySelector('[data-inventory-count]')!;
        return {
          size: parseFloat(getComputedStyle(quantity).fontSize),
          nameSize: parseFloat(getComputedStyle(name).fontSize),
          muted: getComputedStyle(quantity).color !== getComputedStyle(name).color,
        };
      });
      await expectCompactDiceLabels(choice(page));
      expect(positions.size).toBeLessThan(positions.nameSize);
      expect(positions.muted).toBe(true);
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
    const shopRow = (page: Page, type: string) => dialog(page).locator(`[data-inventory-type="${type}"]`);
    const shopButton = (page: Page, type: string, action: 'buy' | 'sell') => shopRow(page, type).getByRole('button', {
      name: action === 'buy' ? words.buyDie : words.sellDie, exact: true,
    });
    const shopBalance = async (page: Page, count: number) => {
      await expect(dialog(page).locator('[data-shop-balance]')).toHaveText(String(count));
      await expect(dialog(page).locator('[data-shop-balance]')).toHaveAttribute('aria-label', words.balance.replace('{{count}}', String(count)));
    };
    const ownedText = (count: number) => words.owned.replace('{{count}}', String(count));

    test('shop buys and sells immediately, enforces stock and balance limits, and persists', async ({ page }) => {
      await seedInventory(page, stock({ even: 5 }, 2, ['electors']));
      await page.reload();
      await menu(page, words.shop);
      await expect(dialog(page).locator('[data-inventory-type]')).toHaveCount(20);
      expect(await dialog(page).locator('[data-inventory-type]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-inventory-type'))))
        .toEqual(englishOrder.filter((type) => !['normal', 'merchant'].includes(type)));
      await expect(shopButton(page, 'aranka', 'sell')).toBeDisabled();
      await press(shopButton(page, 'even', 'buy'));
      await shopBalance(page, 0);
      await expect(page.locator('[data-merchant-balance]')).toHaveText('0');
      await expect(shopRow(page, 'even').locator('[data-inventory-count]')).toHaveText(ownedText(6));
      await expect(shopButton(page, 'even', 'buy')).toBeDisabled();
      await expect(shopButton(page, 'aranka', 'buy')).toBeDisabled();
      await press(shopButton(page, 'even', 'sell'));
      await shopBalance(page, 1);
      await expect(shopButton(page, 'even', 'buy')).toBeDisabled();
      await press(shopButton(page, 'even', 'sell'));
      await shopBalance(page, 2);
      await expect(shopButton(page, 'even', 'buy')).toBeEnabled();
      await press(shopButton(page, 'aranka', 'buy'));
      await shopBalance(page, 0);
      await expect(shopButton(page, 'aranka', 'sell')).toBeEnabled();
      await press(shopButton(page, 'aranka', 'sell'));
      await expect(shopButton(page, 'aranka', 'sell')).toBeDisabled();
      await expect(shopRow(page, 'aranka').locator('[data-inventory-count]')).toHaveText(ownedText(0));
      expect(await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.inventory')!)))
        .toEqual(stock({ even: 4 }, 1, ['electors']));
      await page.keyboard.press('Escape');
      await menu(page, words.myDice);
      await expect(shopRow(page, 'even').locator('[data-inventory-count]')).toHaveText('4 / 6');
      await page.reload();
      await press(page.getByRole('button', { name: words.balance.replace('{{count}}', '1'), exact: true }));
      await shopBalance(page, 1);
      await expect(shopRow(page, 'even').locator('[data-inventory-count]')).toHaveText(ownedText(4));
    });

    test('shop trades preserve current dice and replace only unavailable copies in the next chooser', async ({ page }) => {
      await seedInventory(page, stock({ even: 2, odd: 1 }, 2));
      await page.reload();
      await start(page, 'beggars', { even: 2, odd: 1, merchant: 2 });
      const currentDice = await table(page).locator('[data-die-id]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-die-type')));
      const saved = await page.evaluate(() => localStorage.getItem('cogita.farkle.loadout'));
      await menu(page, words.shop);
      await press(shopButton(page, 'weighted', 'buy'));
      await press(shopButton(page, 'even', 'sell'));
      await press(shopButton(page, 'even', 'sell'));
      await press(shopButton(page, 'weighted', 'buy'));
      expect(await table(page).locator('[data-die-id]').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-die-type')))).toEqual(currentDice);
      await page.keyboard.press('Escape');
      await menu(page, words.newGame);
      await press(dialog(page).getByRole('button', { name: words.chooseDice, exact: true }));
      await expect(chosenCount(page, 'normal')).toHaveText('5');
      await expect(chosenCount(page, 'odd')).toHaveText('1');
      await expect(chosenCount(page, 'weighted')).toHaveText('0');
      expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.loadout'))).toBe(saved);
      await beginCustom(page);
      expect(await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.loadout')!)))
        .toEqual({ ...defaultLoadout(), normal: 5, odd: 1 });
    });

    test('shop retries the same failed trade once and blocks further trades while saving', async ({ page }) => {
      await seedInventory(page, stock({ even: 2 }, 4, ['beggars']));
      await page.reload();
      await menu(page, words.shop);
      for (const [action, count, balance] of [['buy', 3, 2], ['sell', 2, 3]] as const) {
        const previous = await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'));
        await page.evaluate(() => {
          const set = Storage.prototype.setItem;
          let fail = true;
          Storage.prototype.setItem = function (key, value) {
            if (key === 'cogita.farkle.inventory' && fail) { fail = false; throw new DOMException('Test quota', 'QuotaExceededError'); }
            set.call(this, key, value);
          };
        });
        await press(shopButton(page, 'even', action));
        await expect(dialog(page).getByRole('alert')).toContainText(words.inventorySaveError);
        await shopBalance(page, balance);
        await expect(shopRow(page, 'even').locator('[data-inventory-count]')).toHaveText(ownedText(count));
        for (const { id } of SPECIAL_TYPES) for (const kind of ['buy', 'sell'] as const) await expect(shopButton(page, id, kind)).toBeDisabled();
        expect(await page.evaluate(() => localStorage.getItem('cogita.farkle.inventory'))).toBe(previous);
        await press(dialog(page).getByRole('button', { name: words.retryStorage, exact: true }));
        await expect(dialog(page).getByRole('alert')).toHaveCount(0);
        expect(await page.evaluate(() => JSON.parse(localStorage.getItem('cogita.farkle.inventory')!)))
          .toEqual(stock({ even: count }, balance, ['beggars']));
      }
      await seedInventory(page, stock({ even: 1 }, Number.MAX_SAFE_INTEGER));
      await page.reload();
      await menu(page, words.shop);
      await expect(shopButton(page, 'even', 'sell')).toBeDisabled();
    });

    test('shop layout keeps its balance visible and supports probability cards and responsive columns', async ({ page }, testInfo) => {
      await seedInventory(page, stock({}, 2));
      await page.reload();
      await menu(page, words.shop);
      const modal = dialog(page);
      await expect(modal.locator('[data-shop-prices]')).toHaveText(words.shopPrices.replace('{{buy}}', '2').replace('{{sell}}', '1'));
      await expect(shopRow(page, 'aranka').getByRole('button')).toHaveText([words.dice.aranka, words.sellDie, words.buyDie]);
      if (!touch) await page.mouse.move(0, 0);
      for (const viewport of touch ? [{ width: 390, height: 844, columns: 1 }]
        : [{ width: 1366, height: 900, columns: 3 }, { width: 1024, height: 768, columns: 2 }, { width: 390, height: 844, columns: 1 }]) {
        await page.setViewportSize(viewport);
        await expect.poll(() => modal.locator('.farkle-dice-grid').evaluate((node) => getComputedStyle(node).gridTemplateColumns.split(' ').length)).toBe(viewport.columns);
        expect(await modal.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
        expect(await modal.locator('[data-inventory-type]').evaluateAll((nodes) => nodes.every((node) => node.scrollWidth <= node.clientWidth))).toBe(true);
        await expectCompactDiceLabels(modal);
        // Read the header together so a resize cannot mix coordinates from different frames.
        const { title, balance, prices } = await modal.evaluate((node) => ({
          title: node.querySelector('[data-slot="dialog-title"]')!.getBoundingClientRect().toJSON(),
          balance: node.querySelector('[data-shop-balance]')!.getBoundingClientRect().toJSON(),
          prices: node.querySelector('[data-shop-prices]')!.getBoundingClientRect().toJSON(),
        }));
        expect(balance.x).toBeGreaterThan(title.x + title.width);
        expect(Math.abs(balance.y + balance.height / 2 - title.y - title.height / 2)).toBeLessThan(1);
        expect(prices.y).toBeGreaterThanOrEqual(title.y + title.height);
        await page.screenshot({ path: testInfo.outputPath(`shop-${viewport.width}.png`) });
      }
      const name = shopRow(page, 'aranka').getByRole('button', { name: words.dice.aranka, exact: true });
      if (touch) await shopRow(page, 'aranka').locator('[data-inventory-count]').tap();
      else await shopRow(page, 'aranka').locator('[data-inventory-count]').hover();
      await expect(page.locator('[data-dice-probabilities="aranka"]')).toHaveCount(0);
      if (touch) await press(name); else await name.focus();
      await expect(page.locator('[data-dice-probabilities="aranka"]')).toBeVisible();
      await expect(page.locator('[data-dice-probabilities="aranka"] [data-probability-face]')).toHaveCount(6);
      await modal.getByRole('heading').click();
      await page.setViewportSize({ width, height: 320 });
      await shopRow(page, 'weighted').scrollIntoViewIfNeeded();
      await expect.poll(() => modal.locator('.farkle-dice-list').evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true);
      for (const node of [modal.getByRole('heading'), modal.locator('[data-shop-balance]'), modal.locator('[data-shop-prices]')]) {
        const bounds = (await node.boundingBox())!;
        expect(bounds.y).toBeGreaterThanOrEqual(16);
        expect(bounds.y + bounds.height).toBeLessThanOrEqual(304);
      }
      await page.screenshot({ path: testInfo.outputPath('shop-short.png') });
    });

    test('inventory, shop and all ten match targets', async ({ page }) => {
      await expect(table(page).locator('canvas')).toHaveCount(1);
      await expect(page.locator('.farkle-hud')).toHaveCount(0);
      await menu(page, words.myDice);
      const inventory = page.getByRole('dialog', { name: words.myDice, exact: true });
      await expect(inventory.locator('li')).toHaveCount(22);
      await expect(inventory.locator('img')).toHaveCount(22);
      await expect(inventory.locator('[data-inventory-count]')).toHaveText(englishOrder.map((type) => type === 'normal' ? '6 / 6' : type === 'merchant' ? '0 / ∞' : '0 / 6'));
      await page.keyboard.press('Escape');
      if (touch) await expect(page.locator('[data-sidebar="trigger"]')).toBeFocused();
      else await expect(sidebar(page).getByRole('button', { name: words.myDice, exact: true })).toBeFocused();
      await press(page.getByRole('button', { name: words.balance.replace('{{count}}', '0'), exact: true }));
      await expect(page.getByRole('dialog', { name: words.shop, exact: true })).toHaveCount(1);
      await page.keyboard.press('Escape');
      for (const { id, target } of LEVELS) {
        await start(page, id);
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
        const dx = next.x + next.width / 2 - prior.x - prior.width / 2;
        const dy = next.y + next.height / 2 - prior.y - prior.height / 2;
        const forward = key === 'a' ? -dx : key === 'd' ? dx : key === 'w' ? -dy : dy;
        expect(forward).toBeGreaterThanOrEqual(-3);
        expect(Math.abs(key === 'a' || key === 'd' ? dy : dx)).toBeLessThanOrEqual(forward + 3);
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
    test('touch hints follow the last selection without falling back', async ({ page }, testInfo) => {
      test.skip(!touch, 'Desktop retains independent hover hints.');
      await start(page, 'masters');
      const hint = page.locator('.farkle-face-icon[data-hint-source="touch"]');
      const first = die(page, 'B0'), second = die(page, 'B1');
      await expect(hint).toHaveCount(0);
      await first.tap();
      await expect(hint).toHaveAttribute('data-hint-die-id', 'B0');
      await expect(hint).toHaveAttribute('data-face-value', '5');
      await expect(hint.locator('.farkle-die-name')).toHaveText(words.dice.normal);
      await expect(page.locator('[data-hovered="true"]')).toHaveCount(0);
      await second.tap();
      await expect(hint).toHaveAttribute('data-hint-die-id', 'B1');
      await expect(first).toHaveAttribute('aria-pressed', 'true');
      await second.tap();
      await expect(hint).toHaveCount(0);
      await expect(first).toHaveAttribute('aria-pressed', 'true');
      await second.tap();
      await first.tap();
      await expect(hint).toHaveCount(0);
      await expect(second).toHaveAttribute('aria-pressed', 'true');
      await first.tap();
      await expect(hint).toHaveAttribute('data-hint-die-id', 'B0');
      await openSidebar(page);
      await expect(hint).toHaveCount(0);
      await page.keyboard.press('Escape');
      await expect(hint).toHaveAttribute('data-hint-die-id', 'B0');
      await menu(page, words.myDice);
      await expect(hint).toHaveCount(0);
      await page.keyboard.press('Escape');
      await expect(hint).toHaveAttribute('data-hint-die-id', 'B0');
      for (const viewport of [{ width: 390, height: 844 }, { width: 844, height: 390 }]) {
        await page.setViewportSize(viewport);
        await expect.poll(async () => {
          const dieBox = (await first.boundingBox())!, hintBox = (await hint.boundingBox())!;
          return hintBox.y - dieBox.y - dieBox.height;
        }).toBeGreaterThan(0);
        const tableBox = (await table(page).boundingBox())!, hintBox = (await hint.boundingBox())!;
        expect(hintBox.x).toBeGreaterThanOrEqual(tableBox.x);
        expect(hintBox.x + hintBox.width).toBeLessThanOrEqual(tableBox.x + tableBox.width);
        expect(hintBox.y + hintBox.height).toBeLessThanOrEqual(tableBox.y + tableBox.height);
        expect(await hint.evaluate((node) => getComputedStyle(node).pointerEvents)).toBe('none');
        await page.screenshot({ path: testInfo.outputPath(`touch-hint-${viewport.width}.png`) });
      }
      await page.keyboard.press('d');
      await expect(hint).toHaveCount(0);
      await expect(page.locator('[data-hovered="true"]')).toHaveCount(1);
      await first.tap();
      await expect(hint).toHaveCount(0);
      await first.tap();
      await expect(hint).toHaveAttribute('data-hint-die-id', 'B0');
      const tableBox = (await table(page).boundingBox())!;
      await page.mouse.move(tableBox.x + 4, tableBox.y + 20);
      await expect(hint).toHaveCount(0);
      await expect(page.locator('[data-hovered="true"]')).toHaveCount(0);
      await second.hover();
      await expect(hint).toHaveCount(0);
      await expect(second).toHaveAttribute('data-hovered', 'true');
      await first.tap();
      await expect(hint).toHaveCount(0);
      await first.tap();
      await expect(hint).toHaveAttribute('data-hint-die-id', 'B0');
      await page.getByRole('button', { name: words.scoreContinue, exact: true }).tap();
      await expect(hint).toHaveCount(0);
      await settled(page);
      await expect(hint).toHaveCount(0);
      await die(page, 'B2').tap();
      await expect(hint).toHaveAttribute('data-hint-die-id', 'B2');
      await page.getByRole('button', { name: words.pass, exact: true }).tap();
      await expect(hint).toHaveCount(0);
      await expect(table(page)).toHaveAttribute('data-player', 'A');
      await expect(page.locator('[data-hint-source="hover"]')).toBeVisible();
      await expect(hint).toHaveCount(0);
      await page.setViewportSize({ width: 390, height: 844 });
      await start(page, 'masters');
      await expect(hint).toHaveCount(0);
      await die(page, 'B0').tap();
      await expect(hint).toHaveCount(1);
      await start(page, 'masters');
      await expect(hint).toHaveCount(0);
      await die(page, 'B0').tap();
      await menu(page, words.exitGame);
      await expect(hint).toHaveCount(0);
      await start(page, 'masters');
      await expect(hint).toHaveCount(0);
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
      await expect(page.locator('.farkle-face-icon')).toHaveAttribute('data-face-value', 'wild');
      await expect(page.locator('.farkle-die-name')).toHaveText(words.dice.devil);
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
      await expect(sidebar(page).locator('.sidebar-header [data-sidebar="menu-button"]')).toHaveText([words.newGame, words.customGame, words.myDice, words.shop, words.settings]);
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
      await menu(page, words.settings);
      await expect(page.getByRole('dialog', { name: words.settings, exact: true })).toBeVisible();
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
      // Keep both matches on the same known single-Even loadout; this tests retry,
      // not the strength of a newly sampled dynamic combination.
      await page.evaluate(() => {
        const previous = Math.random, samples = [0, 0];
        Math.random = () => samples.length ? samples.shift()! : previous();
      });
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
      await expect(page.locator('[data-inventory-type="normal"] [data-inventory-count]')).toHaveText('6 / 6');
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
        } else {
          await die(page, `B${index}`).tap();
          await expect(page.locator('.farkle-face-icon')).toHaveAttribute('data-hint-die-id', `B${index}`);
          await expect(page.locator('.farkle-die-name')).toHaveText(words.dice[type]);
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
        if (specials.length) await adjust(page, specials[0].id, true);
        expect((await choice(page).boundingBox())!.width).toBe(Math.min(width - 32, maxWidth));
        await expectCompactDiceLabels(choice(page));
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
      await adjust(page, 'aranka', true);
      await expect(row(page, 'aranka').locator('[data-selected-count]')).toHaveText('1');
      await expect(choice(page).getByRole('button', { name: words.startGame, exact: true })).toBeEnabled();
      await page.setViewportSize({ width, height: 320 });
      await expect.poll(columns).toBe(touch ? 1 : 3);
      await expect.poll(() => choice(page).locator('.farkle-dice-list').evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true);
      await row(page, 'weighted').scrollIntoViewIfNeeded();
      for (const node of [choice(page).getByRole('heading'),
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
      await menu(page, words.settings);
      await press(page.getByRole('dialog').getByRole('button', { name: words.opponentModes.random, exact: true }));
      await page.keyboard.press('Escape');
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
      await expect(page.locator('[data-inventory-type="merchant"] [data-inventory-count]')).toHaveText('5 / ∞');
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
