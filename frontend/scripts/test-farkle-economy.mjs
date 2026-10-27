import assert from 'node:assert/strict';
import { createModuleLoader } from './module-loader.mjs';

const load = createModuleLoader();
const { DICE_TYPES, SPECIAL_TYPES, difficultyFor, rollValues } = (await load('../src/components/playground/farkle/dice.ts')).exports;
const { drawOpponentDice } = (await load('../src/components/playground/farkle/opponentDice.ts')).exports;
const { LEVELS, newInventory, emptySpecial, inventoryPool, readInventory, saveInventory, awardDice, INVENTORY_KEY,
  INVENTORY_ACTIONS, canModifyInventory, modifyInventory, DICE_BUY_PRICE, DICE_SELL_PRICE, canTradeDice, tradeDice } =
  (await load('../src/components/playground/farkle/economy.ts')).exports;
const { evaluateDice } = (await load('../src/components/playground/farkle/scoring.ts')).exports;
const { gameReducer, initialGame } = (await load('../src/components/playground/farkle/state.ts')).exports;
const { rewardGroups } = (await load('../src/components/playground/farkle/rewards.ts')).exports;
const { defaultLoadout, loadoutSize, loadoutDice, readLoadout, saveLoadout, LOADOUT_KEY } =
  (await load('../src/components/playground/farkle/loadout.ts')).exports;
const { clearFarkleStorage } = (await load('../src/components/playground/farkle/storage.ts')).exports;

assert.deepEqual(LEVELS.map(({ id, target, special, merchant, firstWin }) => [id, target, special, merchant, firstWin]), [
  ['beggars', 1500, 2, 1, 1], ['wagoners', 2000, 2, 1, 1], ['masters', 3000, 3, 2, 2], ['courtiers', 4000, 3, 2, 2],
  ['burgomasters', 5000, 3, 3, 3], ['stewards', 6000, 3, 3, 3], ['governors', 7000, 4, 3, 3],
  ['chancellors', 8000, 4, 3, 3], ['burgraves', 9000, 4, 4, 4], ['electors', 10000, 4, 4, 4],
]);
const maintained = { special: { ...emptySpecial(), even: 2 }, merchant: 2000, firstWins: ['beggars', 'electors'] };
assert.equal(DICE_BUY_PRICE, 2);
assert.equal(DICE_SELL_PRICE, 1);
for (const { id } of SPECIAL_TYPES) {
  const initial = { ...newInventory(), merchant: 12, firstWins: ['beggars'] };
  let inventory = initial;
  assert.equal(canTradeDice(inventory, id, 'sell'), false);
  for (let count = 1; count <= 6; count++) {
    assert.equal(canTradeDice(inventory, id, 'buy'), true);
    inventory = tradeDice(inventory, id, 'buy');
    assert.equal(inventory.special[id], count);
    assert.equal(inventory.merchant, 12 - count * 2);
    assert.deepEqual(inventory.firstWins, ['beggars']);
  }
  assert.equal(canTradeDice({ ...inventory, merchant: 10 }, id, 'buy'), false, 'Six copies is the cap');
  assert.equal(canTradeDice({ ...inventory, merchant: Number.MAX_SAFE_INTEGER }, id, 'sell'), false);
  assert.equal(canTradeDice({ ...inventory, merchant: Number.MAX_SAFE_INTEGER - 1 }, id, 'sell'), true);
  assert.equal(tradeDice({ ...inventory, merchant: Number.MAX_SAFE_INTEGER - 1 }, id, 'sell').merchant, Number.MAX_SAFE_INTEGER);
  for (let count = 5; count >= 0; count--) {
    assert.equal(canTradeDice(inventory, id, 'sell'), true);
    inventory = tradeDice(inventory, id, 'sell');
    assert.equal(inventory.special[id], count);
    assert.equal(inventory.merchant, 6 - count);
  }
  assert.equal(canTradeDice(inventory, id, 'sell'), false);
  for (const merchant of [0, 1]) assert.equal(canTradeDice({ ...inventory, merchant }, id, 'buy'), false);
  assert.equal(canTradeDice({ ...inventory, merchant: 2 }, id, 'buy'), true);
  assert.deepEqual(initial, { ...newInventory(), merchant: 12, firstWins: ['beggars'] }, 'Trades leave their input unchanged');
  assert.deepEqual(inventory.special, emptySpecial(), 'Trading one type leaves the rest unchanged');
}
const filled = modifyInventory(maintained, 'fillDice');
assert.deepEqual(Object.values(filled.special), Array(20).fill(6));
assert.equal(filled.merchant, 999, 'Fill overwrites balances above 999');
assert.deepEqual(modifyInventory(maintained, 'clearDice'), { ...newInventory(), firstWins: maintained.firstWins });
assert.deepEqual(modifyInventory(maintained, 'addMerchantDice'), { ...maintained, merchant: 2999 });
assert.equal(modifyInventory(modifyInventory(maintained, 'addMerchantDice'), 'addMerchantDice').merchant, 3998);
assert.deepEqual(modifyInventory(maintained, 'clearMerchantDice'), { ...maintained, merchant: 0 });
for (const action of INVENTORY_ACTIONS) {
  const next = modifyInventory(maintained, action);
  assert.deepEqual(next.firstWins, maintained.firstWins);
  assert.equal(inventoryPool(next).normal, 6);
}
assert.equal(maintained.merchant, 2000, 'Maintenance does not mutate its source');
assert.equal(maintained.special.even, 2);
assert.equal(canModifyInventory({ ...maintained, merchant: Number.MAX_SAFE_INTEGER - 999 }, 'addMerchantDice'), true);
assert.equal(canModifyInventory({ ...maintained, merchant: Number.MAX_SAFE_INTEGER - 998 }, 'addMerchantDice'), false);
const cache = new Map(['cogita.farkle.inventory', 'cogita.farkle.loadout', 'cogita.farkle.settings', 'cogita.farkle.customGame',
  'cogita.locale', 'unrelated'].map((key) => [key, '{broken']));
let failRemoval = true;
const cacheStorage = { removeItem(key) {
  if (key === 'cogita.farkle.settings' && failRemoval) throw new Error('denied');
  cache.delete(key);
} };
assert.throws(() => clearFarkleStorage(cacheStorage), /denied/);
failRemoval = false;
clearFarkleStorage(cacheStorage);
clearFarkleStorage(cacheStorage);
assert.deepEqual([...cache.keys()], ['cogita.locale', 'unrelated'], 'Reset retries remove only the four owned keys');

const expectedWeights = {
  lucky: [6, 1, 2, 3, 4, 6], unlucky: [1, 3, 2, 2, 2, 1], favourable: [6, 0, 1, 1, 6, 4],
  pie: [6, 1, 3, 3, 0, 0], misfortune: [1, 5, 5, 5, 5, 1], monk: [8, 8, 1, 1, 1, 1],
  strip: [4, 2, 2, 2, 3, 3], unbalanced: [3, 4, 1, 1, 2, 1], shrinking: [2, 1, 1, 1, 1, 3],
  painted: [3, 1, 1, 1, 7, 3], heavenly: [7, 2, 2, 2, 2, 4], grimy: [1, 5, 1, 1, 7, 1],
  lu: [3, 3, 3, 3, 3, 8], ci: [3, 3, 3, 3, 3, 8], fer: [3, 3, 3, 3, 3, 8], aranka: [6, 1, 6, 1, 6, 1],
};
assert.equal(DICE_TYPES.length, 22);
assert.equal(SPECIAL_TYPES.length, 20);
assert.deepEqual(DICE_TYPES.map(({ id }) => id), ['normal', 'even', 'odd', 'devil', 'weighted', ...Object.keys(expectedWeights), 'merchant']);
for (const [id, weights] of Object.entries(expectedWeights)) assert.deepEqual(DICE_TYPES.find((die) => die.id === id).weights, weights);
for (const die of DICE_TYPES) {
  const sum = die.weights.reduce((a, b) => a + b);
  let cumulative = 0, previousFace = 0;
  die.weights.forEach((weight, index) => {
    if (!weight) return;
    assert.deepEqual(rollValues([die.id], () => (cumulative + weight / 2) / sum), [index + 1]);
    if (cumulative) {
      assert.deepEqual(rollValues([die.id], () => (cumulative - 1e-8) / sum), [previousFace]);
      assert.deepEqual(rollValues([die.id], () => (cumulative + 1e-8) / sum), [index + 1]);
    }
    cumulative += weight;
    previousFace = index + 1;
  });
  assert.deepEqual(rollValues([die.id], () => 0), [1]);
  assert.deepEqual(rollValues([die.id], () => 1 - Number.EPSILON), [previousFace]);
  for (let sample = 0; sample < 1000; sample++) {
    const [face] = rollValues([die.id], () => sample / 1000);
    assert.ok(die.weights[face - 1] > 0, `${die.id}: zero-probability faces never roll`);
  }
}
assert.deepEqual(DICE_TYPES.find((die) => die.id === 'even').weights, [1, 4, 1, 4, 1, 4]);
assert.deepEqual(DICE_TYPES.find((die) => die.id === 'odd').weights, [4, 1, 4, 1, 4, 1]);
assert.deepEqual(DICE_TYPES.find((die) => die.id === 'weighted').weights, [10, 1, 1, 1, 1, 1]);
assert.equal(difficultyFor(1500), 0.15);
assert.equal(difficultyFor(4000), 0.4);
assert.equal(difficultyFor(20_000), 1);
assert.deepEqual(drawOpponentDice(1500, 'random', () => 0), Array(6).fill('normal'));
assert.deepEqual(drawOpponentDice(1500, 'random', () => 0.999), [...Array(5).fill('normal'), 'aranka']);
assert.deepEqual(drawOpponentDice(4000, 'random', () => 0.999), [...Array(4).fill('normal'), 'aranka', 'aranka']);
for (const [target, min, max] of [[0, 0, 1], [1500, 0, 1], [2000, 0, 1], [2001, 1, 2], [4000, 1, 2],
  [4001, 2, 3], [6000, 2, 3], [6001, 3, 4], [8000, 3, 4], [8001, 3, 5], [10000, 3, 5], [20000, 3, 5]]) {
  for (let wanted = min; wanted <= max; wanted++) {
    let first = true, sequence = 123;
    const result = drawOpponentDice(target, 'random', () => {
      if (first) { first = false; return (wanted - min + 0.5) / (max - min + 1); }
      sequence = (sequence * 1664525 + 1013904223) >>> 0;
      return sequence / 2 ** 32;
    });
    assert.equal(result.length, 6);
    assert.equal(result.filter((type) => type !== 'normal').length, wanted);
    assert.ok(!result.includes('merchant'));
    for (const { id } of SPECIAL_TYPES)
      assert.ok(result.filter((candidate) => candidate === id).length <= (id === 'weighted' ? 1 : 3), `${target}: ${id} cap`);
  }
}
assert.deepEqual(drawOpponentDice(10000, 'random', () => 0.999), ['normal', 'aranka', 'aranka', 'aranka', 'fer', 'fer']);
const firstTypeCounts = (target) => {
  const counts = emptySpecial();
  for (let index = 0; index < 1000; index++) {
    let first = true;
    const dice = drawOpponentDice(target, 'random', () => { if (first) { first = false; return 0.75; } return (index + 0.5) / 1000; });
    counts[dice.find((type) => type !== 'normal')]++;
  }
  return counts;
};
const lower = firstTypeCounts(2000), higher = firstTypeCounts(10000);
assert.deepEqual(Object.values(lower), Array(20).fill(50), 'Every type starts with probability 1/20, including Weighted');
assert.deepEqual(higher, lower, 'Difficulty changes the special count, not type preference');
for (const [index, { id }] of SPECIAL_TYPES.entries()) {
  const rolls = [0.999, (index + 0.5) / 20, (index + 0.5) / 20, (index + 0.5) / 20, (index + 0.5) / 20, (index + 0.5) / 20];
  const dice = drawOpponentDice(10000, 'random', () => rolls.shift());
  assert.equal(dice.filter((type) => type === id).length, id === 'weighted' ? 1 : 3, 'Full types leave the candidate pool');
}

const full = () => ({ special: Object.fromEntries(SPECIAL_TYPES.map(({ id }) => [id, 6])), merchant: 0, firstWins: [] });
assert.deepEqual(Object.values(newInventory().special), Array(20).fill(0));
for (const [index, { id }] of SPECIAL_TYPES.entries()) {
  const { reward } = awardDice(newInventory(), 'beggars', false, () => (index + 0.5) / 20);
  assert.equal(reward.special[id], 1, 'Every new type is obtainable from the uniform reward pool');
}
for (const level of LEVELS) {
  const loss = awardDice(newInventory(), level.id, false, () => 0.999);
  assert.equal(loss.inventory.special.aranka, 1);
  assert.equal(loss.reward.merchant, 0);
  assert.deepEqual(loss.inventory.firstWins, []);
  const win = awardDice(loss.inventory, level.id, true, () => 0);
  assert.equal(win.inventory.special.even, level.special);
  assert.equal(win.reward.merchant, level.merchant + level.firstWin);
  assert.equal(win.reward.firstWin, level.firstWin);
  const repeat = awardDice(win.inventory, level.id, true, () => 0);
  assert.equal(repeat.reward.firstWin, 0);
  assert.equal(repeat.reward.merchant, level.merchant);
  assert.deepEqual(repeat.inventory.firstWins, [level.id]);
  const surplus = awardDice(full(), level.id, true);
  assert.equal(surplus.reward.converted, Math.ceil(level.special / 2));
  assert.equal(surplus.reward.merchant, level.merchant + level.firstWin + Math.ceil(level.special / 2));
}
const almost = full(); almost.special.even = 5; almost.special.odd = 5; almost.firstWins = ['courtiers'];
const result = awardDice(almost, 'courtiers', true, () => 0);
assert.deepEqual(result.reward.special, { ...emptySpecial(), even: 1, odd: 1 });
assert.equal(result.reward.merchant, 3);
assert.deepEqual(result.inventory.special, full().special);
assert.equal(almost.special.even, 5, 'Settlement is pure');
assert.equal(awardDice({ ...almost, firstWins: [] }, 'courtiers', true, () => 0).reward.merchant, 5);
const grouped = rewardGroups(awardDice({ ...almost, firstWins: [] }, 'courtiers', true, () => 0).reward);
assert.deepEqual(grouped, [
  { source: 'regular', entries: [{ type: 'even', count: 1 }, { type: 'odd', count: 1 }, { type: 'merchant', count: 2 }] },
  { source: 'firstWin', entries: [{ type: 'merchant', count: 2 }] },
  { source: 'converted', entries: [{ type: 'merchant', count: 1 }] },
]);
for (const [inventory, won, sources] of [
  [newInventory(), false, ['regular']], [newInventory(), true, ['regular', 'firstWin']],
  [full(), false, ['converted']], [{ ...full(), firstWins: ['courtiers'] }, true, ['regular', 'converted']],
]) {
  const { reward } = awardDice(inventory, 'courtiers', won, () => 0);
  const groups = rewardGroups(reward);
  assert.deepEqual(groups.map(({ source }) => source), sources, 'Only nonempty reward groups are shown, in source order');
  assert.equal(groups.flatMap(({ entries }) => entries).filter(({ type }) => type === 'merchant')
    .reduce((sum, { count }) => sum + count, 0), reward.merchant, 'Display groups never duplicate Merchant rewards');
}
assert.equal(awardDice(full(), 'beggars', false).reward.converted, 1);
const unequal = full(); unequal.special.even = 0; unequal.special.odd = 5;
assert.equal(awardDice(unequal, 'beggars', false, () => 0.6).reward.special.odd, 1, 'Reward chooses types equally, not missing copies');

for (let count = 2; count <= 6; count++) {
  const dice = Array.from({ length: count }, () => ({ type: 'devil', value: 1 }));
  assert.equal(evaluateDice(dice).score, count < 3 ? 0 : 1000 * 2 ** (count - 3));
}
assert.equal(evaluateDice([{ type: 'devil', value: 1 }, { type: 'devil', value: 1 }, { type: 'normal', value: 2 }]).score, 200);
for (const type of Object.keys(expectedWeights)) {
  assert.equal(evaluateDice([{ type, value: 1 }]).score, 100);
  assert.equal(evaluateDice([{ type, value: 6 }]).score, 0);
}
assert.equal(evaluateDice(['lu', 'ci', 'fer'].map((type) => ({ type, value: 6 }))).score, 600);
assert.equal(evaluateDice(Array.from({ length: 3 }, () => ({ type: 'heavenly', value: 6 }))).score, 600);
assert.equal(evaluateDice([2, 3, 4, 5, 6].map((value) => ({ type: 'heavenly', value }))).score, 750);
const mixed = ['normal', 'favourable', 'pie', 'heavenly', 'lu', 'aranka'];
const loadout = { A: mixed, B: mixed };
let game = gameReducer(initialGame, { type: 'start', setup: { kind: 'standard', level: 'courtiers' }, loadout, values: [1, 1, 1, 1, 1, 1] });
const types = game.dice.map(({ id, type }) => [id, type]);
function finish() { game = gameReducer(game, { type: 'complete', id: game.command.id, values: [1, 1, 1, 1, 1, 1], hoverSample: 0 }); }
finish(); finish();
game = gameReducer(game, { type: 'select', id: 'B0', actor: 'human' });
game = gameReducer(game, { type: 'store', actor: 'human' }); finish(); finish();
game = gameReducer(game, { type: 'pass', actor: 'human' }); finish(); finish();
assert.deepEqual(game.dice.map(({ id, type }) => [id, type]), types, 'Rerolls and handoffs keep both loadouts');

let stored = null;
const storage = { getItem(key) { assert.equal(key, INVENTORY_KEY); return stored; }, setItem(key, value) { assert.equal(key, INVENTORY_KEY); stored = value; } };
assert.deepEqual(readInventory(storage), newInventory());
saveInventory(storage, result.inventory);
assert.deepEqual(readInventory(storage), result.inventory);
assert.equal(Object.hasOwn(JSON.parse(stored), 'normal'), false);
stored = JSON.stringify({ ...result.inventory, normal: 999, special: { ...result.inventory.special, normal: 999 } });
assert.equal(inventoryPool(readInventory(storage)).normal, 6);
for (const raw of ['{', 'null', JSON.stringify({ ...newInventory(), merchant: -1 }), JSON.stringify({ ...newInventory(), special: { ...newInventory().special, even: 7 } }), JSON.stringify({ ...newInventory(), firstWins: ['unknown'] })]) {
  stored = raw; assert.throws(() => readInventory(storage)); assert.equal(stored, raw, 'Invalid data is not overwritten');
}
assert.throws(() => saveInventory({ setItem() { throw new Error('quota'); } }, result.inventory), /quota/);
let selectionJson = null;
const selectionStorage = {
  getItem(key) { assert.equal(key, LOADOUT_KEY); return selectionJson; },
  setItem(key, value) { assert.equal(key, LOADOUT_KEY); selectionJson = value; },
};
const selectionPool = { ...defaultLoadout(), even: 1, odd: 2, devil: 1, pie: 1, heavenly: 1, aranka: 2, merchant: 1_000_000_000 };
assert.deepEqual(readLoadout(selectionStorage, selectionPool), defaultLoadout());
const chosen = { ...defaultLoadout(), normal: 2, even: 1, odd: 1, devil: 1, merchant: 1 };
saveLoadout(selectionStorage, chosen);
assert.deepEqual(readLoadout(selectionStorage, selectionPool), chosen);
assert.equal(loadoutSize(chosen), 6);
assert.deepEqual(loadoutDice(chosen), ['normal', 'normal', 'even', 'odd', 'devil', 'merchant']);
const newChosen = { ...defaultLoadout(), normal: 1, pie: 1, heavenly: 1, aranka: 2, merchant: 1 };
saveLoadout(selectionStorage, newChosen);
assert.deepEqual(readLoadout(selectionStorage, selectionPool), newChosen);
assert.deepEqual(loadoutDice(newChosen), ['normal', 'pie', 'heavenly', 'aranka', 'aranka', 'merchant']);
for (const raw of ['{', 'null', '[]', '{}', ...[
  { ...chosen, normal: 1 }, { ...chosen, normal: 3 }, { ...chosen, normal: -1 },
  { ...chosen, normal: 1.5, merchant: 1.5 }, { ...defaultLoadout(), normal: -1, merchant: 7 },
].map(JSON.stringify)]) {
  selectionJson = raw;
  assert.deepEqual(readLoadout(selectionStorage, selectionPool), defaultLoadout());
  assert.equal(selectionJson, raw, 'Reading invalid preferences never writes browser storage');
}
for (const [saved, available, expected] of [
  [chosen, { ...selectionPool, even: 0, merchant: 0 }, { ...chosen, normal: 4, even: 0, merchant: 0 }],
  [{ ...chosen, normal: 0, even: 3 }, selectionPool, chosen],
  [{ ...chosen, normal: 1, weighted: 1 }, selectionPool, chosen],
  [chosen, defaultLoadout(), defaultLoadout()],
]) {
  saveLoadout(selectionStorage, saved);
  const raw = selectionJson;
  assert.deepEqual(readLoadout(selectionStorage, available), expected, 'Only unavailable copies become Normal');
  assert.equal(selectionJson, raw, 'Clipping ownership does not save a new preference');
}
assert.throws(() => readLoadout({ getItem() { throw new Error('blocked'); } }, selectionPool), /blocked/);
assert.throws(() => saveLoadout({ setItem() { throw new Error('quota'); } }, chosen), /quota/);
console.log('Farkle probabilities, loadouts, rewards and browser storage passed.');
