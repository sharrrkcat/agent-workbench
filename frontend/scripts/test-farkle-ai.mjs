import assert from 'node:assert/strict';
import { createModuleLoader } from './module-loader.mjs';

const load = createModuleLoader();
const { FarkleAI } = (await load('../src/components/playground/farkle/ai.ts')).exports;
const { createOpponentPlayback, OPPONENT_TIMING } = (await load('../src/components/playground/farkle/opponentPlayback.ts')).exports;
const { evaluateDice } = (await load('../src/components/playground/farkle/scoring.ts')).exports;
const { rollValues } = (await load('../src/components/playground/farkle/dice.ts')).exports;

const normal = Array(6).fill('normal');
const position = (faces, { types = normal, target = 4000, banked = 0, round = 0 } = {}) => ({
  target, banked, round, dice: types.map((type, index) => ({ id: `A${index}`, player: 'A', index, type,
    value: faces[index] ?? 1, status: index < faces.length ? 'idle' : 'scored' })),
});
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-7, `${actual} != ${expected}`);
const start = performance.now();
const ai = new FarkleAI(normal);
const constructorMs = performance.now() - start;
const hand = [5, 1, 2, 2, 2, 6];
let result = ai.decide(position(hand));
assert.equal(result.action, 'store');
assert.deepEqual(result.dice, ['A1']);
assert.equal(result.score, 100);
assert.equal(result.bankValue, 350);
close(result.continueValue, 427.9487711038397); // Independently enumerated, full-turn normal-dice reference.
result = ai.decide(position(hand, { round: 600 }));
assert.equal(result.action, 'pass');
assert.deepEqual(result.dice, ['A1', 'A2', 'A3', 'A4', 'A0']);
assert.equal(result.score, 350);
close(result.continueValue, 922.9779074004393);

// Same remaining goal and hand: lower difficulty banks a small edge; maximum difficulty takes it.
const cautious = ai.decide(position(hand, { round: 300 }));
const strongest = ai.decide(position(hand, { target: 10000, banked: 6000, round: 300 }));
assert.equal(cautious.action, 'pass');
assert.equal(strongest.action, 'store');
assert.deepEqual(strongest.dice, ['A1']);
close(cautious.continueValue, strongest.continueValue);
close(strongest.continueValue, 667.1058147123807);
assert.equal(ai.decide(position(hand, { target: 1500 })).action, 'store', 'Low difficulty still understands leaving five dice');

for (const target of [1500, 2000, 3000, 4000, 6000, 8000, 10000]) {
  const hot = ai.decide(position([1, 3, 3, 3], { target }));
  assert.deepEqual(hot.dice, ['A0', 'A1', 'A2', 'A3'], 'Every level takes the independent triple and releases six dice');
  assert.equal(hot.score, 400);
  const winning = ai.decide(position(hand, { target, banked: target - 350 }));
  assert.equal(winning.action, 'pass', 'An available win always takes precedence over continuing');
  assert.equal(winning.score, 350);
  assert.equal(winning.continueValue, null);
}
assert.equal(ai.decide(position([1, 2, 3, 4, 5, 6], { target: 1500 })).score, 1500);
assert.equal(ai.decide(position([2, 3, 4, 5, 6], { target: 1500, banked: 750 })).score, 750);
assert.equal(ai.decide(position([1, 1, 1, 1, 1, 1], { target: 4000 })).score, 8000);

const mixedTypes = ['normal', 'normal', 'even', 'odd', 'devil', 'weighted'];
const mixed = new FarkleAI(mixedTypes);
const mixedPosition = position(hand, { types: mixedTypes });
const before = structuredClone(mixedPosition);
result = mixed.decide(mixedPosition);
assert.equal(result.action, 'store');
assert.equal(result.score, 350, 'Keeping the lone Weighted die changes the correct selection');
assert.ok(!result.dice.includes('A5'));
close(result.continueValue, 866.1290274991916);
assert.deepEqual(mixedPosition, before, 'Analysis never edits the board');
assert.deepEqual(mixed.decide({ ...mixedPosition, dice: [...mixedPosition.dice].reverse() }), result, 'Input order does not change die identities');

const singleWeighted = ['normal', 'weighted', 'normal', 'normal', 'normal', 'normal'];
const weighted = new FarkleAI(singleWeighted);
result = weighted.decide(position([1, 1, 2, 3, 4, 6], { types: singleWeighted }));
assert.deepEqual(result.dice, ['A0'], 'Equal visible faces retain the more useful die for rerolling');

const devilTypes = ['devil', 'devil', 'devil', 'normal', 'normal', 'normal'];
const devil = new FarkleAI(devilTypes);
result = devil.decide(position([1, 1, 1], { types: devilTypes, target: 1500, banked: 500 }));
assert.equal(result.action, 'pass');
assert.equal(result.score, 1000);
assert.deepEqual(result.dice, ['A0', 'A1', 'A2']);
const oneDevilTypes = ['devil', 'normal', 'normal', 'normal', 'normal', 'normal'];
const oneDevil = new FarkleAI(oneDevilTypes);
result = oneDevil.decide(position([1, 2, 3, 4, 5], { types: oneDevilTypes, target: 1500, banked: 750 }));
assert.equal(result.score, 750, 'The head fills the high straight, rather than scoring a single one');
assert.equal(result.dice.length, 5);

let seed = 5821;
const random = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 2 ** 32);
for (const [engine, types] of [[ai, normal], [mixed, mixedTypes], [devil, devilTypes]]) {
  for (let sample = 0; sample < 160; sample++) {
    const count = 1 + Math.floor(random() * 6);
    const faces = rollValues(types, random).slice(0, count);
    const current = position(faces, { types, round: Math.floor(random() * 30) * 50 });
    const available = current.dice.filter((die) => die.status === 'idle');
    if (!evaluateDice(available).hasScore) continue;
    const choice = engine.decide(current);
    const selected = available.filter((die) => choice.dice.includes(die.id));
    assert.equal(evaluateDice(selected).valid, true, 'All chosen dice belong to complete scoring combinations');
    assert.equal(evaluateDice(selected).score, choice.score);
    if (choice.action === 'pass') {
      let best = 0;
      for (let mask = 1; mask < 1 << available.length; mask++)
        best = Math.max(best, evaluateDice(available.filter((_, index) => mask & (1 << index))).score);
      assert.equal(choice.score, best, 'Banking never leaves points on the table');
    } else {
      const left = available.filter((die) => !choice.dice.includes(die.id));
      assert.equal(evaluateDice(left).valid, false, 'Continuing does not overlook an independent batch that would give hot dice');
    }
  }
}

// The playback clock is separate from both animation and inference, and can pause mid-delay.
const original = { setTimeout, clearTimeout, performance };
let now = 0, sequence = 0;
const timers = new Map();
globalThis.performance = { now: () => now };
globalThis.setTimeout = (callback, delay) => { const id = ++sequence; timers.set(id, { callback, due: now + delay }); return id; };
globalThis.clearTimeout = (id) => timers.delete(id);
function advance(ms) {
  const end = now + ms;
  while (true) {
    const next = [...timers].filter(([, timer]) => timer.due <= end).sort(([, a], [, b]) => a.due - b.due)[0];
    if (!next) break;
    timers.delete(next[0]); now = next[1].due; next[1].callback();
  }
  now = end;
}
try {
  assert.deepEqual(OPPONENT_TIMING, { think: 1500, select: 550, confirm: 900, handoff: 500 });
  const actions = [];
  const playback = createOpponentPlayback((action) => actions.push(action), false);
  playback.setDecision({ dice: ['A1', 'A2'], action: 'store', score: 200 });
  advance(1499); assert.deepEqual(actions, []);
  advance(1); assert.deepEqual(actions, [{ type: 'hover', id: 'A1' }]);
  advance(549); assert.equal(actions.length, 1);
  advance(1); assert.deepEqual(actions.slice(-2), [{ type: 'select', id: 'A1' }, { type: 'hover', id: 'A2' }]);
  advance(50); playback.setPaused(true);
  advance(10000); assert.equal(actions.length, 3);
  playback.setPaused(false); advance(499); assert.equal(actions.length, 3);
  advance(1); assert.deepEqual(actions.at(-1), { type: 'select', id: 'A2' });
  advance(899); assert.equal(actions.length, 4);
  advance(1); assert.deepEqual(actions.at(-1), { type: 'store' });
  playback.setPaused(true); playback.setPaused(false); advance(10000);
  assert.equal(actions.length, 5, 'A completed move cannot submit twice');

  const delayedActions = [];
  const delayed = createOpponentPlayback((action) => delayedActions.push(action), false);
  advance(2000); assert.equal(delayedActions.length, 0, 'Thinking can finish while calculation is pending');
  delayed.setPaused(true);
  delayed.setDecision({ dice: ['A0'], action: 'pass', score: 100 });
  advance(10000); assert.equal(delayedActions.length, 0);
  delayed.setPaused(false);
  assert.deepEqual(delayedActions, [{ type: 'hover', id: 'A0' }]);
  advance(550); assert.equal(delayedActions.at(-1).type, 'select');
  advance(900); assert.equal(delayedActions.at(-1).type, 'pass');

  const resumedActions = [];
  const resumed = createOpponentPlayback((action) => resumedActions.push(action), false, ['A0']);
  resumed.setDecision({ dice: ['A0', 'A1'], action: 'pass', score: 200 });
  advance(1500);
  assert.deepEqual(resumedActions, [{ type: 'hover', id: 'A1' }]);
  advance(550); advance(900);
  assert.deepEqual(resumedActions, [{ type: 'hover', id: 'A1' }, { type: 'select', id: 'A1' }, { type: 'pass' }],
    'Retry preserves already selected dice instead of toggling them off');
  const confirmedActions = [];
  const confirmed = createOpponentPlayback((action) => confirmedActions.push(action), false, ['A0']);
  confirmed.setDecision({ dice: ['A0'], action: 'pass', score: 100 });
  advance(1500); assert.equal(confirmedActions.length, 0);
  advance(900); assert.deepEqual(confirmedActions, [{ type: 'pass' }], 'A fully selected retry still shows its confirmation pause');

  for (const delay of [0, 1600, 2100]) {
    const cancelled = [];
    const pending = createOpponentPlayback((action) => cancelled.push(action), false);
    pending.setDecision({ dice: ['A0'], action: 'pass', score: 100 });
    advance(delay); pending.dispose();
    const beforeCancel = [...cancelled];
    pending.setDecision({ dice: ['A1'], action: 'store', score: 100 });
    pending.setPaused(false); advance(10000);
    assert.deepEqual(cancelled, beforeCancel, 'Exit/restart cancels thinking, selection and confirmation');
  }
  const initiallyPaused = [];
  const pending = createOpponentPlayback((action) => initiallyPaused.push(action), true);
  pending.setDecision({ dice: ['A0'], action: 'pass', score: 100 });
  advance(10000); assert.equal(initiallyPaused.length, 0);
  pending.setPaused(false); advance(1499); assert.equal(initiallyPaused.length, 0);
  advance(1); assert.equal(initiallyPaused[0].type, 'hover');
  pending.dispose();
} finally {
  globalThis.setTimeout = original.setTimeout;
  globalThis.clearTimeout = original.clearTimeout;
  globalThis.performance = original.performance;
}

console.log(`Farkle exact turn values, rational difficulty, typed selections and pausable AI timing passed (normal kernel ${constructorMs.toFixed(0)}ms).`);
