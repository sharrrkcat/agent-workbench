import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createModuleLoader } from './module-loader.mjs';

const load = createModuleLoader();
const { defaultLoadout, FULL_DICE_POOL, loadoutSize, canAdjustLoadout, adjustLoadout, randomLoadout } =
  (await load('../src/components/playground/farkle/loadout.ts')).exports;
const { CUSTOM_GAME_KEY, CUSTOM_OPPONENT_MODES, defaultCustomGame, targetError, readCustomGame, saveCustomGame } =
  (await load('../src/components/playground/farkle/customGame.ts')).exports;
const { gameReducer, initialGame } = (await load('../src/components/playground/farkle/state.ts')).exports;
const english = JSON.parse(readFileSync(new URL('../src/i18n/resources/en/common.json', import.meta.url))).farkle.dice;
const order = Object.keys(FULL_DICE_POOL).sort((a, b) => english[a].localeCompare(english[b], 'en'));
const pool = { ...FULL_DICE_POOL, even: 1, merchant: 1000 };
let counts = defaultLoadout();
function adjust(type, change) {
  assert.equal(canAdjustLoadout(counts, pool, type, change), true);
  counts = adjustLoadout(counts, type, change, order);
  assert.equal(loadoutSize(counts), 6);
  assert.ok(Object.values(counts).every((count) => Number.isInteger(count) && count >= 0));
  assert.equal(canAdjustLoadout(counts, pool, 'normal', -1), false);
}
assert.equal(canAdjustLoadout(counts, pool, 'normal', 1), false);
for (const type of ['weighted', 'merchant', 'even', 'misfortune', 'aranka', 'odd']) adjust(type, 1);
assert.equal(counts.normal, 0);
for (const type of order.filter((type) => type !== 'normal')) assert.equal(canAdjustLoadout(counts, pool, type, 1), false);
for (const removed of ['aranka', 'misfortune', 'even', 'merchant', 'odd', 'weighted']) {
  adjust('normal', 1);
  assert.equal(counts[removed], 0, `Normal replaces ${english[removed]} in full English order`);
}
adjust('even', 1);
assert.equal(canAdjustLoadout(counts, pool, 'even', 1), false);
adjust('even', -1);
assert.equal(canAdjustLoadout(counts, pool, 'even', -1), false);
for (const type of order.filter((type) => type !== 'normal')) {
  const copies = Math.min(6, pool[type]);
  for (let i = 0; i < copies; i++) adjust(type, 1);
  for (let i = 0; i < copies; i++) adjust(type, -1);
}

assert.deepEqual(randomLoadout(defaultLoadout(), () => 0.99), defaultLoadout(), 'Normal dice alone fill every slot');
const limitedStock = Object.freeze({ ...defaultLoadout(), even: 2, merchant: 2 });
assert.deepEqual(randomLoadout(limitedStock, () => 0.999), { ...defaultLoadout(), normal: 2, even: 2, merchant: 2 },
  'Sampling without replacement cannot repeat an exhausted copy or select an unowned type');
const firstDrawCounts = { normal: 0, even: 0, odd: 0 };
for (let first = 0; first < 9; first++) {
  let calls = 0;
  const result = randomLoadout({ ...defaultLoadout(), even: 1, odd: 2 }, () => calls++ === 0 ? (first + 0.5) / 9 : 0);
  assert.equal(calls, 6);
  // The final five draws are Normal, so the remaining copy identifies the first draw.
  firstDrawCounts.normal += result.normal - 5;
  firstDrawCounts.even += result.even;
  firstDrawCounts.odd += result.odd;
}
assert.deepEqual(firstDrawCounts, { normal: 6, even: 1, odd: 2 }, 'Every owned copy has equal probability');
const seededRandom = (seed) => () => ((seed = (1664525 * seed + 1013904223) >>> 0) / 2 ** 32);
const seen = new Set();
for (let seed = 0; seed < 128; seed++) {
  for (const available of [limitedStock, Object.freeze({ ...FULL_DICE_POOL })]) {
    const selected = randomLoadout(available, seededRandom(seed));
    assert.equal(loadoutSize(selected), 6);
    for (const type of order) {
      assert(Number.isInteger(selected[type]) && selected[type] >= 0 && selected[type] <= available[type]);
      if (selected[type]) seen.add(type);
    }
  }
  const capped = randomLoadout({ ...FULL_DICE_POOL, merchant: 6 }, seededRandom(seed));
  for (const merchant of [7, 999, Number.MAX_SAFE_INTEGER]) {
    assert.deepEqual(randomLoadout({ ...FULL_DICE_POOL, merchant }, seededRandom(seed)), capped,
      'Merchant balance above six must not change probability or allocate extra copies');
  }
}
assert.deepEqual([...seen].sort(), [...order].sort(), 'The full stock can supply all 22 types, including Normal and Merchant');
assert.deepEqual(limitedStock, { ...defaultLoadout(), even: 2, merchant: 2 }, 'Random allocation leaves inventory unchanged');

for (const target of [2, 1501, 10000, 10001, 10 ** 12, Number.MAX_SAFE_INTEGER - 1]) assert.equal(targetError(String(target)), null);
for (const input of ['', ' ', '1.5', '1.0', '1e3', '0x10', '+1', ' 1', '1 ', 'Infinity', 'NaN']) {
  assert.equal(targetError(input), 'integer', input);
}
for (const input of ['0', '-1', '1', '0001', '-999999999999999999999']) assert.equal(targetError(input), 'minimum');
for (const input of ['9007199254740991', '9007199254740992', '999999999999999999999']) assert.equal(targetError(input), 'maximum');
assert.equal(targetError('0002'), null);
const saved = new Map();
const storage = { getItem: (key) => saved.get(key) ?? null, setItem: (key, value) => saved.set(key, value) };
assert.deepEqual(readCustomGame(storage), defaultCustomGame());
assert.equal(saved.size, 0);
for (const mode of CUSTOM_OPPONENT_MODES) {
  const config = { target: 1501, opponentDiceMode: mode, opponentLoadout: { ...defaultLoadout(), normal: 0, weighted: 6 },
    playerLoadout: { ...defaultLoadout(), normal: 0, merchant: 6 } };
  saveCustomGame(storage, config);
  assert.deepEqual(readCustomGame(storage), config);
  assert.deepEqual(Object.keys(JSON.parse(saved.get(CUSTOM_GAME_KEY))).sort(), ['opponentDiceMode', 'opponentLoadout', 'playerLoadout', 'target']);
  assert.equal(JSON.parse(saved.get(CUSTOM_GAME_KEY)).opponentLoadout, 'eeeeee');
  assert.equal(JSON.parse(saved.get(CUSTOM_GAME_KEY)).playerLoadout, 'vvvvvv');
  assert.deepEqual([...saved.keys()], [CUSTOM_GAME_KEY], 'Custom games only save their own configuration');
}
for (const type of order) {
  const loadout = { ...defaultLoadout(), normal: 0, [type]: 6 };
  const config = { ...defaultCustomGame(), opponentLoadout: loadout, playerLoadout: loadout };
  saveCustomGame(storage, config);
  assert.deepEqual(readCustomGame(storage), config, `Both custom sides allow six ${type} dice`);
}
const encodedCustom = { target: 1500, opponentDiceMode: 'dynamic', opponentLoadout: 'aaaaaa', playerLoadout: 'aaaaaa' };
for (const value of [null, [], {}, defaultCustomGame(), ...[0, 1, 1.5, Number.MAX_SAFE_INTEGER].map((target) => ({ ...encodedCustom, target })),
  { ...encodedCustom, opponentDiceMode: 'invalid' }, { ...encodedCustom, opponentLoadout: 'zzzzzz' },
  { ...encodedCustom, opponentLoadout: 'aaaaa' }, { ...encodedCustom, playerLoadout: 'aaaaaaa' },
  { ...encodedCustom, playerLoadout: defaultLoadout() },
  { target: 1501, opponentDiceMode: 'custom', opponentLoadout: 'aaaaaa' }]) {
  saved.set(CUSTOM_GAME_KEY, JSON.stringify(value));
  assert.deepEqual(readCustomGame(storage), defaultCustomGame());
  assert.equal(saved.get(CUSTOM_GAME_KEY), JSON.stringify(value), 'Invalid custom settings are not rewritten');
}
saved.set(CUSTOM_GAME_KEY, '{broken');
assert.deepEqual(readCustomGame(storage), defaultCustomGame());
assert.equal(saved.get(CUSTOM_GAME_KEY), '{broken');
assert.throws(() => readCustomGame({ getItem() { throw Error('blocked'); } }), /blocked/);
assert.throws(() => saveCustomGame({ setItem() { throw Error('quota'); } }, defaultCustomGame()), /quota/);

for (const target of [2, 1500, 1501, 10000, 10001, 10 ** 12, Number.MAX_SAFE_INTEGER - 1]) {
  const setup = { kind: 'custom', config: { ...defaultCustomGame(), target } };
  let game = gameReducer(initialGame, { type: 'start', startedAt: 1793100000123, opponentDiceMode: 'dynamic', setup,
    loadout: { A: Array(6).fill('normal'), B: Array(6).fill('normal') }, values: [1, 1, 1, 1, 1, 1] });
  assert.equal(game.target, target);
  assert.deepEqual(game.setup, setup);
  const finish = () => { game = gameReducer(game, { type: 'complete', id: game.command.id, values: [1, 1, 1, 1, 1, 1], hoverSample: 0 }); };
  finish(); finish();
  const before = Math.floor((target - 1) / 50) * 50;
  game = { ...game, totals: { A: 0, B: before } };
  game = gameReducer(game, { type: 'pass', actor: 'human' });
  assert.equal(game.winner, null, 'The real target is not capped at 10000');
  while (game.command) finish();
  game = { ...game, player: 'B', rounds: { A: 0, B: 100 } };
  game = gameReducer(game, { type: 'pass', actor: 'human' });
  assert.equal(game.winner, 'B');
}
console.log('Farkle six-die balancing, English replacement order, custom storage and safe integer targets passed.');
