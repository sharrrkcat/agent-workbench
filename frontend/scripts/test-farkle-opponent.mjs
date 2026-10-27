import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { createModuleLoader, mockModule, sourceUrl } from './module-loader.mjs';

const load = createModuleLoader();
const { drawOpponentDice, decodeCombination, OPPONENT_DICE_MODES } =
  (await load('../src/components/playground/farkle/opponentDice.ts')).exports;
const { DICE_TYPES, SPECIAL_TYPES, rollValues } = (await load('../src/components/playground/farkle/dice.ts')).exports;
const { DEFAULT_OPPONENT_MODE, FARKLE_SETTINGS_KEY, readFarkleSettings, saveFarkleSettings } =
  (await load('../src/components/playground/farkle/settings.ts')).exports;
const asset = JSON.parse(readFileSync(new URL('../src/components/playground/farkle/calibration.json', import.meta.url), 'utf8'));
const sha = (value) => createHash('sha256').update(JSON.stringify(value)).digest('hex');

assert.equal(asset.formatVersion, 1);
assert.equal(asset.gamesPerCombination, 2000);
assert.equal(asset.source.target, 5000);
assert.equal(asset.source.policy, 1);
assert.equal(asset.source.experimentDigest, '85199883f4572ef248d981b8431007709d4bd5824d8e3a1a642d7169a260c059');
assert.equal(asset.source.candidatesSha256, 'acab0c4510f7adc9599c170d64b9d395671c90645c115d2969f93f04b75affbd');
assert.equal(sha(DICE_TYPES.map(({ id, weights }) => [id, weights])), asset.source.catalogSha256,
  'Changing the dice distributions requires replacing the calibration artifact');
assert.equal(sha(asset.pools), '1dad879dd30f2a4effe2593d207912f4b90b1640f441350d7138c37a501bdcdb',
  'Every packed code and score matches the independently verified frozen source');
assert.deepEqual(asset.types, SPECIAL_TYPES.map(({ id }) => id));
assert.deepEqual(asset.pools.map((rows) => rows.length / 2), [20, 209, 1520, 8626, 40584]);

const encode = (dice) => dice.filter((type) => type !== 'normal').map((type) => asset.types.indexOf(type))
  .sort((a, b) => a - b).reduce((code, index) => code * 20 + index, 0);
const byPool = asset.pools.map((rows, index) => {
  const records = new Map();
  for (let offset = 0; offset < rows.length; offset += 2) {
    const code = rows[offset], wins = rows[offset + 1], dice = decodeCombination(index + 1, code);
    assert(Number.isInteger(code) && code >= 0 && code < 20 ** (index + 1));
    assert(Number.isInteger(wins) && wins >= 0 && wins <= 2000);
    assert.equal(dice.length, 6);
    assert.equal(dice.filter((type) => type === 'normal').length, 5 - index);
    assert(dice.every((type) => type === 'normal' || asset.types.includes(type)));
    for (const type of new Set(dice.filter((type) => type !== 'normal')))
      assert(dice.filter((item) => item === type).length <= (type === 'weighted' ? 1 : 3));
    assert.equal(encode(dice), code);
    assert(!records.has(code)); records.set(code, wins);
  }
  return records;
});
assert.deepEqual(asset.pools.map((rows) => rows.slice(0, 2)), [[19, 1221], [399, 1504], [7999, 1678], [143999, 1607], [2871999, 1555]]);
assert.notEqual(encode(['lu', 'lu', 'ci']), encode(['lu', 'ci', 'ci']), 'Named equivalents keep distinct probability mass');
assert.equal(byPool[4].has(encode(['lu', 'lu', 'lu', 'ci', 'ci'])), true, 'Copy caps apply to names before mechanical equivalence');

const sample = (target, mode, values) => {
  const remaining = [...values];
  const result = drawOpponentDice(target, mode, () => {
    assert(remaining.length, 'Draw must consume exactly the supplied random samples'); return remaining.shift();
  });
  assert.equal(remaining.length, 0); return result;
};
for (const target of [-100, 0, 1500, 2000]) {
  assert.deepEqual(sample(target, 'dynamic', [0]), Array(6).fill('normal'));
  for (let index = 0; index < 20; index++) {
    assert.deepEqual(sample(target, 'dynamic', [0.75, (index + 0.5) / 20]),
      [...Array(5).fill('normal'), asset.types[index]], 'Every single special die is equally eligible, regardless of score');
  }
}

const rules = [
  [2000.00001, [[1], [2, 40, 60]]], [4000, [[1], [2, 40, 60]]],
  [4000.00001, [[2, 50, 80], [3, 50, 70]]], [6000, [[2, 50, 80], [3, 50, 70]]],
  [6000.00001, [[3, 50, 80], [4, 50, 80]]], [8000, [[3, 50, 80], [4, 50, 80]]],
  [8000.00001, [[3, 50, 90], [4, 50, 80], [5, 50, 80]]],
  [10000, [[3, 50, 90], [4, 50, 80], [5, 50, 80]]], [12000, [[3, 50, 90], [4, 50, 80], [5, 50, 80]]],
];
for (const [target, branches] of rules) {
  const frequencies = new Map();
  for (let index = 0; index < 600; index++) {
    const dice = sample(target, 'dynamic', [(index + 0.5) / 600, 0.25]);
    const count = dice.filter((type) => type !== 'normal').length;
    frequencies.set(count, (frequencies.get(count) ?? 0) + 1);
  }
  assert.deepEqual([...frequencies], branches.map(([pool]) => [pool, 600 / branches.length]), 'Pool choice has equal probability');
  for (const [branchIndex, [pool, lower, upper]] of branches.entries()) {
    if (pool === 1) continue;
    const candidates = [...byPool[pool - 1]].filter(([, wins]) => wins > lower * 20 && wins <= upper * 20);
    const reached = new Set();
    for (let index = 0; index < candidates.length; index++) {
      const dice = sample(target, 'dynamic', [(branchIndex + 0.5) / branches.length, (index + 0.5) / candidates.length]);
      const code = encode(dice);
      assert.equal(code, candidates[index][0], 'Equal random intervals select every named configuration exactly once');
      reached.add(code);
    }
    assert.equal(reached.size, candidates.length);
    for (const [code, wins] of byPool[pool - 1]) {
      if (wins === lower * 20) assert(!reached.has(code), 'The lower endpoint is excluded');
      if (wins === upper * 20) assert(reached.has(code), 'The upper endpoint is included');
    }
  }
}

// Some real strata have no record exactly at a boundary. Exercise every endpoint
// with a tiny artifact fixture, using real legal codes and deliberately chosen scores.
const endpointScores = [799, 800, 801, 999, 1000, 1001, 1199, 1200, 1201, 1399, 1400, 1401, 1599, 1600, 1601, 1799, 1800, 1801];
const fixture = { ...asset, pools: asset.pools.map((rows) => endpointScores.flatMap((wins, index) => [rows[index * 2], wins])) };
const fixtureLoader = createModuleLoader({
  [sourceUrl('components/playground/farkle/calibration.json')]: mockModule({ default: fixture }),
});
const { drawOpponentDice: drawAtBoundary } = (await fixtureLoader('../src/components/playground/farkle/opponentDice.ts')).exports;
for (const [target, branches] of rules) for (const [branchIndex, [pool, lower, upper]] of branches.entries()) {
  if (pool === 1) continue;
  const expected = endpointScores.flatMap((wins, index) => wins > lower * 20 && wins <= upper * 20 ? [fixture.pools[pool - 1][index * 2]] : []);
  for (let index = 0; index < expected.length; index++) {
    const samples = [(branchIndex + 0.5) / branches.length, (index + 0.5) / expected.length];
    assert.equal(encode(drawAtBoundary(target, 'dynamic', () => samples.shift())), expected[index]);
    assert.equal(samples.length, 0);
  }
}

// Golden digest captured from the original sequential draw, before its extraction.
const randomResults = [];
for (const target of [-100, 0, 1500, 2000, 2001, 4000, 4001, 6000, 6001, 8000, 8001, 10000, 12000]) {
  for (let seed = 1; seed <= 128; seed++) {
    let state = seed;
    randomResults.push(drawOpponentDice(target, 'random', () => {
      state = (Math.imul(state, 1664525) + 1013904223) >>> 0; return state / 2 ** 32;
    }));
  }
}
assert.equal(sha(randomResults), '4582813104fee33b6ecba1aee7d4d622c68706dfad3899dcee3e80e608bd5136');
for (const [index, { id }] of DICE_TYPES.entries()) for (const target of [0, 1500, 10000]) {
  assert.deepEqual(sample(target, 'wild', Array(6).fill((index + 0.5) / 22)), Array(6).fill(id));
}
const slots = Array.from({ length: 6 }, () => new Map());
for (let trial = 0; trial < 22; trial++) {
  const dice = sample(4000, 'wild', Array.from({ length: 6 }, (_, slot) => ((trial + slot * 7) % 22 + 0.5) / 22));
  dice.forEach((type, index) => slots[index].set(type, (slots[index].get(type) ?? 0) + 1));
}
for (const counts of slots) assert.deepEqual([...counts.values()], Array(22).fill(1));

let stored = null;
const storage = {
  getItem(key) { assert.equal(key, FARKLE_SETTINGS_KEY); return stored; },
  setItem(key, value) { assert.equal(key, FARKLE_SETTINGS_KEY); stored = value; },
};
assert.equal(DEFAULT_OPPONENT_MODE, 'dynamic');
for (const raw of [null, '{', 'null', '[]', '1', '{}', '{"opponentDiceMode":"invalid"}']) {
  stored = raw;
  assert.equal(readFarkleSettings(storage), 'dynamic');
  assert.equal(stored, raw, 'Defaults do not overwrite missing or invalid preferences');
}
for (const mode of OPPONENT_DICE_MODES) {
  saveFarkleSettings(storage, mode);
  assert.deepEqual(JSON.parse(stored), { opponentDiceMode: mode });
  assert.equal(readFarkleSettings(storage), mode);
}
assert.throws(() => readFarkleSettings({ getItem() { throw new Error('denied'); } }), /denied/);
assert.throws(() => saveFarkleSettings({ setItem() { throw new Error('quota'); } }, 'wild'), /quota/);

const { FarkleAI } = (await load('../src/components/playground/farkle/ai.ts')).exports;
const { evaluateDice, scoreSubsets } = (await load('../src/components/playground/farkle/scoring.ts')).exports;
for (const types of [Array(6).fill('weighted'), Array(6).fill('devil'), Array(6).fill('merchant'), Array(6).fill('pie'),
  ['merchant', 'weighted', 'weighted', 'devil', 'pie', 'heavenly']]) {
  const ai = new FarkleAI(types);
  let slot = 0;
  for (const values of [Array(6).fill(1), rollValues(types, () => (++slot - 0.5) / 6)]) {
    const dice = types.map((type, index) => ({ id: `A${index}`, player: 'A', index, type, value: values[index], status: 'idle' }));
    const decision = ai.decide({ target: 4000, banked: 0, round: 0, dice });
    if (decision.score === 0) assert.equal(Math.max(...scoreSubsets(dice)), 0);
    else {
      assert(decision.dice.every((id) => dice.some((die) => die.id === id)));
      assert.equal(new Set(decision.dice).size, decision.dice.length);
      assert.equal(evaluateDice(dice.filter((die) => decision.dice.includes(die.id))).score, decision.score);
      assert(['store', 'pass'].includes(decision.action));
    }
  }
}
console.log('Farkle: 50,959 calibrated combinations, all dynamic branches, original random parity, wild loadouts and settings verified.');
