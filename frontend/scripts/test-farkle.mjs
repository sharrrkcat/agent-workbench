import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as THREE from 'three';
import { createModuleLoader, mockModule } from './module-loader.mjs';

const load = createModuleLoader();
const { initialGame, gameReducer, selection, canPlay, canHumanPlay } = (await load('../src/components/playground/farkle/state.ts')).exports;
const { evaluateDice, isWild } = (await load('../src/components/playground/farkle/scoring.ts')).exports;
const { RollPlayback, FACE_NORMALS, FACE_VALUES } = (await load('../src/components/playground/farkle/playback.ts')).exports;
const { tableLayout, placeCamera } = (await load('../src/components/playground/farkle/layout.ts')).exports;
const rolls = JSON.parse(readFileSync(new URL('../src/components/playground/farkle/rolls.json', import.meta.url), 'utf8'));
const { nextHoveredDie } = (await load('../src/components/playground/farkle/input.ts')).exports;
const values = [1, 2, 3, 4, 5, 6];
const loadout = { A: ['normal', 'devil', 'even', 'odd', 'weighted', 'merchant'], B: ['normal', 'devil', 'even', 'odd', 'weighted', 'merchant'] };
const fives = [5, 5, 5, 5, 5, 5];
const bustFaces = [2, 2, 3, 3, 4, 6];
const finish = (state, faces = fives, hoverSample = 0) => gameReducer(state, {
  type: 'complete', id: state.command.id, hoverSample, values: faces,
});
const start = (target = 1500, faces = values) => finish(finish(gameReducer(initialGame, { type: 'start', target, loadout, values: faces })));
const input = (state, action) => gameReducer(state, { ...action, actor: state.player === 'A' ? 'ai' : 'human', revision: state.revision });
const select = (state, ...ids) => ids.reduce((next, id) => input(next, { type: 'select', id }), state);
const store = (state) => input(state, { type: 'store' });
const pass = (state) => input(state, { type: 'pass' });
const diceFor = (faces) => faces.map((value) => ({ value: value === 'wild' ? 1 : value, type: value === 'wild' ? 'devil' : 'normal' }));
function score(faces, expected) {
  const dice = diceFor(faces), before = JSON.stringify(dice);
  for (const order of [dice, [...dice].reverse()]) {
    const result = evaluateDice(order);
    assert.equal(result.score, expected, `Score ${faces}`);
    assert.equal(result.valid, expected > 0, `Validity ${faces}`);
  }
  assert.equal(JSON.stringify(dice), before, 'Scoring does not rewrite physical faces');
}
for (const [faces, expected] of [
  [[], 0], [[1], 100], [[5], 50], [[1, 1], 200], [[5, 5], 100], [[1, 5], 150],
  [[2], 0], [[1, 2], 0], [[2, 2], 0], [[2, 2, 3, 3, 4, 4], 0],
  [[1, 2, 3, 4, 5], 500], [[2, 3, 4, 5, 6], 750], [[1, 2, 3, 4, 5, 6], 1500],
  [[1, 1, 2, 3, 4, 5], 600], [[2, 3, 4, 5, 5, 6], 800],
  [[1, 1, 1, 5, 5, 5], 1500], [[2, 2, 2, 3, 3, 3], 500],
  [[2, 2, 2, 1, 5], 350], [[2, 2, 2, 1, 4], 0],
  [['wild'], 0], [['wild', 1], 0], [['wild', 5], 0], [['wild', 2], 0],
  [['wild', 1, 5], 0], [['wild', 1, 1], 1000], [['wild', 2, 2], 200],
  [['wild', 1, 1, 1], 2000], [['wild', 2, 3, 4, 5], 750],
  [['wild', 1, 2, 3, 4], 500], [['wild', 1, 2, 4, 5, 6], 1500],
  [['wild', 1, 1, 2, 3, 4], 600], [['wild', 2, 2, 1, 5], 350],
]) score(faces, expected);
for (const [face, expected] of [[1, [1000, 2000, 4000, 8000]], [2, [200, 400, 800, 1600]],
  [3, [300, 600, 1200, 2400]], [4, [400, 800, 1600, 3200]], [5, [500, 1000, 2000, 4000]], [6, [600, 1200, 2400, 4800]]]) {
  for (let count = 3; count <= 6; count++) {
    score(Array(count).fill(face), expected[count - 3]);
    score(['wild', ...Array(count - 1).fill(face)], expected[count - 3]);
  }
}
assert.equal(evaluateDice(diceFor([1, 2])).hasScore, true, 'Invalid whole selection can contain a scoring subset');
assert.equal(evaluateDice(diceFor(['wild', 1])).hasScore, true, 'Natural one keeps a roll alive');
assert.equal(evaluateDice(diceFor(['wild', 2, 3, 4])).hasScore, false, 'A wildcard does not score as a single');
assert.equal(evaluateDice(diceFor(bustFaces)).hasScore, false);
assert.equal(evaluateDice(diceFor(['wild', 2, 2, 3, 4])).hasScore, true);
assert.equal(isWild({ type: 'devil', value: 2 }), false);
assert.equal(isWild({ type: 'even', value: 1 }), false);

for (const target of [1500, 2000, 3000, 4000]) {
  const reset = gameReducer(initialGame, { type: 'start', target, loadout, values });
  const roll = finish(reset);
  assert.equal(roll.command.kind, 'roll', 'Starting immediately rolls the active side');
  assert.equal(roll.command.dice.length, 6);
  assert.equal(roll.target, target);
  assert.equal(roll.player, 'B');
  assert.equal(roll.matchId, reset.revision);
  assert.equal(roll.busy, true);
  assert.equal(finish(roll).hoverId, 'B0');
  assert.equal(finish(roll, fives, null).hoverId, null, 'Touch has no automatic hover');
}
let game = start();
assert.equal(game.dice.length, 12);
assert.equal(new Set(game.dice.map((die) => die.id)).size, 12);
assert.equal(store(initialGame), initialGame);
assert.equal(pass(initialGame), initialGame);
assert.equal(store(game), game, 'No empty batches');
assert.equal(select(game, 'A0'), game, 'Only the turn owner is operable');
const invalid = select(game, 'B0', 'B1');
assert.equal(selection(invalid).score, 0);
assert.equal(store(invalid), invalid);
assert.equal(pass(invalid), invalid);
game = select(game, 'B0');
assert.equal(game.busy, false, 'Selection does not move dice');
assert.equal(selection(game).score, 100);
assert.equal(game.hoverId, 'B0', 'Hover and selection coexist');
game = select(game, 'B0');
assert.equal(selection(game).score, 0);

game = store(select(game, 'B0'));
assert.equal(game.command.kind, 'store');
assert.equal(game.dice[6].status, 'selected', 'Scored starts after the whole batch arrives');
assert.equal(game.rounds.B, 0);
for (const action of [{ type: 'select', id: 'B1' }, { type: 'store' }, { type: 'pass' }])
  assert.equal(input(game, action), game);
const storing = game;
game = finish(game);
assert.equal(game.command.kind, 'roll');
assert.equal(game.command.dice.length, 5);
assert.ok(game.command.dice.every((die) => die.id !== 'B0'));
assert.deepEqual(game.batches.B, [['B0']]);
assert.equal(game.rounds.B, 100);
assert.equal(selection(game).score, 0);
assert.equal(gameReducer(game, { type: 'complete', id: storing.command.id, hoverSample: 0, values }), game);
game = finish(game);
assert.equal(game.hoverId, 'B1');
assert.equal(select(game, 'B0'), game, 'Scored dice cannot be retrieved');
assert.equal(input(game, { type: 'hover', id: 'B0' }), game);
game = finish(store(select(game, 'B3', 'B1', 'B2')));
assert.deepEqual(game.batches.B, [['B0'], ['B1', 'B2', 'B3']], 'Each submission keeps a separate sorted row');
assert.equal(game.rounds.B, 600);
assert.equal(game.command.dice.length, 2);
game = finish(game);
game = finish(store(select(game, 'B4', 'B5')));
assert.deepEqual(game.batches.B, []);
assert.equal(game.command.dice.length, 6, 'All six scored clears the batches and rolls all six');
assert.equal(game.rounds.B, 700);
assert.ok(game.dice.every((die) => die.status === 'idle'));
game = finish(game);
game = select(game, 'B0');
assert.equal(game.turnId, start().turnId, 'Selections, storage and rerolls preserve the turn identity');
const nextTurn = pass(start());
assert.ok(nextTurn.turnId > game.turnId, 'Handoff changes the turn identity');
const restarted = gameReducer(game, { type: 'start', target: 1500, loadout, values });
assert.ok(restarted.turnId > game.turnId, 'Restarting B creates a fresh turn identity');
assert.ok(restarted.matchId > game.matchId, 'Restarting replaces the match identity');
assert.equal(gameReducer(game, { type: 'exit' }).turnId, 0);
assert.equal(gameReducer(game, { type: 'exit' }).matchId, 0);
assert.equal(canHumanPlay(game), true);
assert.equal(selection(game).score, 50);
const opponent = finish(finish(pass(start())));
assert.equal(opponent.player, 'A');
assert.equal(opponent.hoverId, null, 'The AI owns its hover, including on fine pointers');
assert.equal(canPlay(opponent), true);
assert.equal(canHumanPlay(opponent), false);
for (const action of [{ type: 'select', id: 'A0' }, { type: 'hover', id: 'A0' }, { type: 'hover', id: null }, { type: 'store' }, { type: 'pass' }]) {
  assert.equal(gameReducer(opponent, { ...action, actor: 'human' }), opponent, 'Human input cannot operate A');
  assert.equal(gameReducer(opponent, { ...action, actor: 'ai', revision: opponent.revision - 1 }), opponent, 'Stale AI actions cannot operate a later roll');
}
const opponentHover = input(opponent, { type: 'hover', id: 'A0' });
assert.equal(opponentHover.hoverId, 'A0');
assert.equal(gameReducer(opponentHover, { type: 'hover', id: null, actor: 'human' }), opponentHover, 'Touch cannot clear AI hover');
assert.equal(select(opponentHover, 'A0').dice[0].status, 'selected');
assert.equal(gameReducer(game, { type: 'pass', actor: 'ai', revision: game.revision }), game, 'AI input cannot operate B');
game = finish(pass(game));
assert.equal(game.totals.B, 750);
assert.equal(game.rounds.B, 0);
assert.equal(selection(game, 'B').score, 0);
assert.equal(game.command.kind, 'view');
assert.equal(game.command.from, 'B');
assert.equal(game.command.to, 'A');
assert.equal(game.player, 'A');
game = finish(game);
assert.equal(game.command.kind, 'roll');
assert.equal(game.command.dice.length, 6);
assert.deepEqual(game.batches.A, []);
game = finish(game);
game = pass(game);
assert.equal(game.player, 'A', 'The outgoing opponent remains visible during its end-of-turn pause');
assert.equal(game.command.kind, 'turnEnd');
assert.equal(game.totals.A, 0);
game = finish(game);
assert.equal(game.player, 'B', 'Empty zero-round pass hands off after the pause');
assert.equal(game.command.kind, 'view');
game = finish(game);
assert.equal(game.command.dice.length, 6);
assert.deepEqual(game.batches.B, []);
assert.ok(game.dice.filter((die) => die.player === 'B').every((die) => die.status === 'idle'));
game = finish(game);
game = finish(finish(store(select(game, 'B0'))));
game = pass(game);
assert.equal(game.totals.B, 800, 'Empty selection banks the accumulated round');
assert.equal(game.rounds.B, 0);

game = store(select(start(3000, [5, 1, 1, 6, 2, 3]), 'B2', 'B0'));
assert.deepEqual(game.command.dice, ['B2', 'B0'], 'Sort by face, then fixed index');
const firstBust = start(1500, bustFaces);
assert.equal(firstBust.command.kind, 'bust');
assert.equal(firstBust.busy, true);
assert.equal(firstBust.rounds.B, 0);
assert.equal(firstBust.hoverId, null);
assert.equal(pass(firstBust), firstBust);
game = finish(finish(finish(firstBust)));
assert.equal(game.player, 'A');
assert.equal(canPlay(game), true);
assert.deepEqual(game.totals, { A: 0, B: 0 });

const opponentBanked = finish(pass(select(opponent, 'A0')));
assert.equal(opponentBanked.totals.A, 50, 'Banked points are visible before the camera moves');
assert.equal(opponentBanked.rounds.A, 0);
assert.equal(opponentBanked.player, 'A');
assert.equal(opponentBanked.turnId, opponent.turnId, 'The player notice waits until the pause ends');
assert.equal(opponentBanked.command.kind, 'turnEnd');
assert.equal(canPlay(opponentBanked), false);
assert.equal(selection(opponentBanked).score, 0);
assert.equal(finish(opponentBanked).command.kind, 'view');
assert.equal(finish(opponentBanked).command.to, 'B');
const opponentBust = finish(finish(store(select(opponent, 'A0')), bustFaces), bustFaces);
assert.equal(opponentBust.command.kind, 'bust');
const opponentBusted = finish(opponentBust);
assert.equal(opponentBusted.command.kind, 'turnEnd', 'Bust keeps its notice, then the opponent pause');
assert.equal(opponentBusted.player, 'A');
assert.equal(opponentBusted.rounds.A, 0);
assert.equal(opponentBusted.totals.A, 0);
assert.equal(finish(opponentBusted).command.to, 'B');
for (const paused of [opponentBanked, opponentBusted]) {
  for (const action of [{ type: 'select', id: 'A1' }, { type: 'hover', id: 'A1' }, { type: 'store' }, { type: 'pass' }])
    assert.equal(input(paused, action), paused, 'No input can change the completed opponent turn');
}

// Even an unbanked round above the goal can be lost. Old scored dice cannot rescue the roll.
game = start(1500, fives);
game = finish(store(select(game, 'B0', 'B1', 'B2', 'B3', 'B4')), [2, 2, 2, 2, 2, 2]);
assert.equal(game.rounds.B, 2000);
assert.equal(game.winner, null);
game = finish(game);
assert.equal(game.command.kind, 'bust');
assert.equal(game.rounds.B, 0);
assert.equal(game.totals.B, 0);
const laterBust = game;
game = finish(finish(finish(game)));
assert.equal(game.player, 'A');
assert.equal(game.totals.B, 0);

// Wildcard alone is a bust even though the physical face value is one.
game = start(1500, fives);
game = finish(store(select(game, 'B0', 'B2', 'B3', 'B4', 'B5')), [2, 1, 2, 2, 2, 2]);
assert.equal(game.command.dice[0].id, 'B1');
assert.equal(finish(game).command.kind, 'bust');

for (const player of ['B', 'A']) for (const target of [1500, 2000]) {
  game = start(target, fives);
  if (player === 'A') game = finish(finish(pass(game)));
  game = select(game, ...game.dice.filter((die) => die.player === player).slice(0, 5).map((die) => die.id));
  assert.equal(selection(game).score, 2000);
  assert.equal(game.winner, null, 'Selection alone cannot win');
  game = finish(pass(game));
  assert.equal(game.winner, player, 'Pass wins at or above the goal');
  assert.equal(game.player, player);
  assert.equal(game.command, null);
  assert.equal(game.totals[player], 2000);
  assert.equal(game.rounds[player], 0);
  assert.equal(selection(game).score, 0);
  assert.equal(canPlay(game), false);
  for (const action of [{ type: 'select', id: `${player}5` }, { type: 'hover', id: `${player}5` },
    { type: 'store' }, { type: 'pass' }]) assert.equal(input(game, action), game);
}
game = start(1500, fives);
for (const ids of [['B0', 'B1', 'B2'], ['B3', 'B4', 'B5'], ['B0', 'B1', 'B2']])
  game = finish(finish(store(select(game, ...ids))));
assert.equal(game.rounds.B, 1500);
assert.equal(game.winner, null);
game = pass(game);
assert.equal(game.winner, 'B', 'An empty selection can bank the winning round');
assert.equal(game.totals.B, 1500);

const phases = [storing, laterBust, firstBust, opponentBanked, opponentBusted, pass(start()), finish(pass(start())), game];
for (const previous of phases) for (const type of ['start', 'exit']) {
  let reset = gameReducer(previous, type === 'start' ? { type, target: 4000, loadout, values } : { type });
  assert.deepEqual(reset.totals, { A: 0, B: 0 });
  assert.deepEqual(reset.rounds, { A: 0, B: 0 });
  assert.deepEqual(reset.batches, { A: [], B: [] });
  assert.equal(reset.winner, null);
  assert.equal(reset.player, 'B');
  if (previous.command) assert.equal(gameReducer(reset, {
    type: 'complete', id: previous.command.id, hoverSample: 0, values,
  }), reset, 'Previous animations and bust timers cannot complete after reset');
  reset = finish(reset);
  assert.equal(reset.playing, type === 'start');
  assert.equal(reset.dice.length, type === 'start' ? 12 : 0);
}

const points = [
  { id: 'center', index: 0, x: 100, y: 100 }, { id: 'left', index: 1, x: 40, y: 100 },
  { id: 'up', index: 2, x: 100, y: 40 }, { id: 'right', index: 3, x: 160, y: 100 },
  { id: 'down', index: 4, x: 100, y: 160 }, { id: 'tie', index: 5, x: 160, y: 100 },
];
for (const [direction, expected] of [['w', 'up'], ['a', 'left'], ['s', 'down'], ['d', 'right']])
  assert.equal(nextHoveredDie(points, 'center', direction), expected);
assert.equal(nextHoveredDie(points, 'left', 'a'), 'left', 'No directional candidate retains hover');
assert.equal(nextHoveredDie([], null, 'w'), null);

// Verify all six outcomes and all four rectangular-table symmetries.
let poses = 0;
for (const pool of Object.values(rolls.pools)) for (const trajectory of pool) {
  for (const value of values) for (const mirror of [false, true]) for (const angle of [0, Math.PI]) {
    const dice = Array.from({ length: trajectory.n }, (_, index) => ({ id: String(index), value }));
    const playback = new RollPlayback(trajectory, dice, mirror, angle, 0.94, () => 0.4);
    let first;
    assert.equal(playback.sample(-20, (id, p) => { if (id === '0') first = p.toArray(); }), false);
    playback.sample(0, (id, p) => { if (id === '0') assert.deepEqual(p.toArray(), first); });
    assert.equal(playback.sample(100000, (id, p, q) => {
      assert.ok(p.toArray().every(Number.isFinite));
      assert.ok(Math.abs(q.length() - 1) < 1e-6);
      assert.ok(FACE_NORMALS[FACE_VALUES.indexOf(value)].clone().applyQuaternion(q).y > 0.9985);
      poses++;
    }), true);
  }
}

// Projection checks use the actual camera matrices without a browser or GPU.
const { RIBBON_WIDTH, RIBBON_CENTER_Z } = (await load('../src/components/playground/farkle/tableMaterial.ts')).exports;
for (const [width, height] of [[1110, 844], [1366, 844], [390, 788], [844, 334], [2304, 1200], [320, 1000], [767, 844], [768, 844], [667, 334]]) {
  const compact = width < 768;
  const layout = tableLayout(width, height), camera = new THREE.PerspectiveCamera(24, 1, 0.1, 200);
  for (let row = 0; row < 6; row++) for (let count = 1; count <= 6 - row; count++) for (let column = 0; column < count; column++) {
    const a = layout.slot('A', row, column, count).add(layout.origins.A);
    const b = layout.slot('B', row, column, count).add(layout.origins.B);
    assert.ok(a.distanceTo(new THREE.Vector3(b.x, b.y, -b.z)) < 1e-9, 'Batch rows mirror across the center line');
    const right = layout.slot('B', row, count - 1, count);
    assert.equal(right.x, layout.slot('B', 0, 0, 1).x, 'Every row shares the same right anchor');
    assert.equal(a.z, layout.slot('A', row, 0, count).add(layout.origins.A).z, 'One batch stays on one row');
  }
  for (const active of ['A', 'B']) {
    placeCamera(camera, layout, layout.views[active]);
    const elevation = Math.atan2(camera.position.y - 0.5, camera.position.z - layout.views[active].z) * 180 / Math.PI;
    assert.ok(Math.abs(elevation - 85) < 1e-9);
    const direction = active === 'A' ? -1 : 1;
    const dividerY = new THREE.Vector3(0, 0.012, 0).project(camera).y * direction;
    assert.ok(dividerY > 1.01, `The center line stays outside the viewport: ${width} ${active}`);
    const edgeZ = active === 'B' ? (RIBBON_CENTER_Z + RIBBON_WIDTH / 2) : (RIBBON_CENTER_Z - RIBBON_WIDTH / 2);
    const ribbonEdgeY = new THREE.Vector3(0, 0.004, edgeZ).project(camera).y * direction;
    assert.ok(ribbonEdgeY < 1.0, `The golden ribbon remains partially visible in the settled view: ${width} ${active}`);
    if (compact) assert.ok(Math.abs(layout.origins[active].clone().project(camera).x) < 1e-9, 'Narrow viewports center the throwing area');
    const left = layout.origins[active].clone().add(new THREE.Vector3(-0.5, 0.5, 0)).project(camera);
    const right = layout.origins[active].clone().add(new THREE.Vector3(0.5, 0.5, 0)).project(camera);
    const diePixels = (right.x - left.x) * width / 2;
    if (width === 390) assert.ok(diePixels >= 36, 'Portrait dice grow when storage leaves the view');
    if (width === 1110) assert.ok(diePixels >= 60, 'Desktop framing should use the current half');
    for (const player of ['A', 'B']) {
      // All possible row/column positions with at most six dice submitted in total.
      const slots = [];
      for (let row = 0; row < 6; row++) for (let count = 1; count <= 6 - row; count++)
        for (let column = 0; column < count; column++) slots.push(layout.slot(player, row, column, count).add(layout.origins[player]));
      for (const position of slots) for (const x of [-0.55, 0.55]) for (const z of [-0.55, 0.55]) {
        const projected = position.clone().add(new THREE.Vector3(x, 0.5, z)).project(camera);
        const screenX = (projected.x + 1) / 2;
        if (player === active && compact) assert.ok(screenX > 1, 'Every narrow-screen batch stays beyond the right edge');
        else if (player === active) {
          assert.ok(screenX > 0 && screenX < 1, 'The whole right-aligned batch fits without reframing');
          assert.ok(Math.abs(projected.y) < 1, 'All six batch rows fit');
        } else assert.ok(Math.abs(projected.y) > 1, 'Opposite storage is outside the view');
      }
      for (const x of [-4.8, 4.8]) for (const z of [-4.8, 4.8]) {
        const p = layout.origins[player].clone().add(new THREE.Vector3(x, 1.4, z)).project(camera);
        if (player !== active) assert.ok(Math.abs(p.y) > 1, 'Opposite throwing area is outside the view');
      }
    }
    for (const pool of Object.values(rolls.pools)) for (const trajectory of pool)
      for (const mirror of [false, true]) for (const angle of [0, Math.PI]) {
      const playback = new RollPlayback(trajectory, Array.from({ length: trajectory.n }, (_, i) => ({ id: String(i), value: 1 })), mirror, angle, 1, () => 0.4);
      for (let frame = 0; frame < trajectory.frames.length; frame++) playback.sample(frame / trajectory.sampleRate * 1000, (_, position, rotation) => {
        const p = position.clone().add(layout.origins[active]).project(camera);
        assert.ok(Math.abs(p.y) < 0.97, `Airborne dice remain visible: ${width} ${active}`);
        assert.ok(Math.abs(p.x) < 0.97, 'The throw remains visible');
        for (const x of [-0.5, 0.5]) for (const y of [-0.5, 0.5]) for (const z of [-0.5, 0.5]) {
          const corner = new THREE.Vector3(x, y, z).applyQuaternion(rotation).add(position).add(layout.origins[active]).project(camera);
          assert.ok(Math.abs(corner.x) < 1 && Math.abs(corner.y) < 1, 'Whole dice stay visible during playback');
        }
        if (frame === trajectory.frames.length - 1) {
          // At most 6-n dice can already be stored when this pool is played.
          for (let row = 0; row < 6 - trajectory.n; row++) for (let count = 1; count <= 6 - trajectory.n - row; count++)
            for (let column = 0; column < count; column++) {
              const slot = layout.slot(active, row, column, count);
              assert.ok(Math.hypot(position.x - slot.x, position.z - slot.z) > 1.4,
                `Stored dice stay clear of the throw: ${width} ${active} ${trajectory.seed}`);
            }
        }
      });
    }
  }
}

// Circular faces share the existing physical face normals and close without cracks.
const { diceGeometry } = (await load('../src/components/playground/farkle/geometry.ts')).exports;
const heavenly = diceGeometry('roundFaces');
const geometryPositions = heavenly.getAttribute('position'), edges = new Map();
assert.deepEqual(heavenly.boundingBox.min.toArray(), [-0.5, -0.5, -0.5]);
assert.deepEqual(heavenly.boundingBox.max.toArray(), [0.5, 0.5, 0.5]);
for (const [face, normal] of FACE_NORMALS.entries()) {
  const cap = heavenly.groups.find(({ materialIndex }) => materialIndex === face);
  assert.ok(cap, `Physical face ${FACE_VALUES[face]} has its own material group`);
  for (let index = cap.start; index < cap.start + cap.count; index++) {
    const point = new THREE.Vector3().fromBufferAttribute(geometryPositions, index);
    assert.ok(Math.abs(point.dot(normal) - 0.5) < 1e-6, 'Scoring face is flat');
    const distance = point.addScaledVector(normal, -0.5).length();
    assert.ok(distance < 1e-6 || Math.abs(distance - 0.45) < 1e-6, 'Face perimeter is circular');
  }
}
const vertexKey = (index) => new THREE.Vector3().fromBufferAttribute(geometryPositions, index).toArray()
  .map((value) => Math.round(value * 1e6)).join(',');
for (let index = 0; index < geometryPositions.count; index += 3) for (const [a, b] of [[0, 1], [1, 2], [2, 0]]) {
  const key = [vertexKey(index + a), vertexKey(index + b)].sort().join('|');
  edges.set(key, (edges.get(key) ?? 0) + 1);
}
assert.ok([...edges.values()].every((count) => count === 2), 'Every edge meets exactly two triangles, including curved patch seams');
heavenly.dispose();

// Real scene scheduling/cleanup, replacing only the browser and GPU boundaries.
const callbacks = new Map(); let sequence = 0, renders = 0, removed = 0, disposed = 0, completions = 0;
globalThis.window = { devicePixelRatio: 1 };
const uploadedTextures = [];
const context = new Proxy({
  createImageData: (width, height) => ({ data: new Uint8ClampedArray(width * height * 4) }),
  putImageData: (data) => uploadedTextures.push(data.data),
}, { get: (target, key) => target[key] ?? (key === 'createRadialGradient' ? () => ({ addColorStop() {} }) : () => {}) });
globalThis.Path2D = class { constructor(path) { this.path = path; } };
globalThis.document = { createElement: () => ({ getContext: () => context }) };
globalThis.requestAnimationFrame = (callback) => { callbacks.set(++sequence, callback); return sequence; };
globalThis.cancelAnimationFrame = (id) => callbacks.delete(id);
class Renderer {
  domElement = { setAttribute() {}, remove() { removed++; } };
  setPixelRatio() {} setSize() {}
  render(scene, camera) { scene.updateMatrixWorld(); camera.updateMatrixWorld(); renders++; }
  dispose() { disposed++; }
}
const sceneLoad = createModuleLoader({ three: mockModule({ ...THREE, WebGLRenderer: Renderer }) });
const { DiceScene } = (await sceneLoad('../src/components/playground/farkle/scene.ts')).exports;
const { faceCanvas, diceMaterials, dicePreview } = (await load('../src/components/playground/farkle/materials.ts')).exports;
const { DICE_TYPES } = (await load('../src/components/playground/farkle/dice.ts')).exports;
const gameplayRandom = Math.random;
try {
  Math.random = () => { throw new Error('Dice appearance must not use gameplay randomness'); };
  for (const { id } of DICE_TYPES) {
    dicePreview(id);
    for (const face of FACE_VALUES) faceCanvas(id, face);
  }
} finally { Math.random = gameplayRandom; }
for (const { id } of DICE_TYPES) for (const material of diceMaterials(id)) {
  material.map?.dispose(); material.bumpMap?.dispose(); material.dispose();
}
const { tableMaterial, ribbonMaterial, fitTableTexture, fitRibbonTexture } = (await load('../src/components/playground/farkle/tableMaterial.ts')).exports;
const cloth = tableMaterial(), secondCloth = tableMaterial();
assert.deepEqual(uploadedTextures[0], uploadedTextures[2], 'Table cloth color is deterministic');
assert.deepEqual(uploadedTextures[1], uploadedTextures[3], 'Table cloth relief is deterministic');
assert.ok(new Set(uploadedTextures[0]).size > 30, 'The table cloth has color detail rather than a flat fill');
assert.ok(new Set(uploadedTextures[1]).size > 20, 'The table cloth has subtle surface relief');
const ribbon = ribbonMaterial(), secondRibbon = ribbonMaterial();
assert.deepEqual(uploadedTextures[4], uploadedTextures[6], 'Ribbon color is deterministic');
assert.deepEqual(uploadedTextures[5], uploadedTextures[7], 'Ribbon relief is deterministic');
assert.ok(new Set(uploadedTextures[4]).size > 30, 'The ribbon has color detail rather than a flat fill');
assert.ok(new Set(uploadedTextures[5]).size > 20, 'The ribbon has subtle surface relief');




const uvAt = (size, x, z) => {
  fitTableTexture(cloth, size);
  const uv = new THREE.Vector2(x / size + 0.5, z / size + 0.5);
  const color = uv.clone().applyMatrix3(cloth.map.matrix);
  assert.ok(color.distanceTo(uv.clone().applyMatrix3(cloth.bumpMap.matrix)) < 1e-10, 'Color and relief stay aligned');
  return color;
};
for (const [x, z] of [[0, 0], [-5.2, 8.3], [14.8, -19.4]]) {
  assert.ok(uvAt(200, x, z).distanceTo(uvAt(383, x, z)) < 1e-10, 'Resizing never stretches or shifts world-space weave');
}
const ribbonUvAt = (size, x, z) => {
  fitRibbonTexture(ribbon, size);
  const uv = new THREE.Vector2(x / size + 0.5, z / RIBBON_WIDTH + 0.5);
  const color = uv.clone().applyMatrix3(ribbon.map.matrix);
  assert.ok(color.distanceTo(uv.clone().applyMatrix3(ribbon.bumpMap.matrix)) < 1e-10, 'Ribbon color and relief stay aligned');
  return color;
};
for (const [x, z] of [[0, 0], [-5.2, 1.3], [14.8, -2.1]]) {
  assert.ok(ribbonUvAt(200, x, z).distanceTo(ribbonUvAt(383, x, z)) < 1e-10, 'Resizing never stretches or shifts ribbon pattern');
}
for (const material of [cloth, secondCloth, ribbon, secondRibbon]) { material.map.dispose(); material.bumpMap.dispose(); material.dispose(); }
const textureDisposals = [];
const geometryDisposals = [];
const disposeTexture = THREE.Texture.prototype.dispose;
const disposeGeometry = THREE.BufferGeometry.prototype.dispose;
THREE.Texture.prototype.dispose = function () { textureDisposals.push(this); disposeTexture.call(this); };
THREE.BufferGeometry.prototype.dispose = function () { geometryDisposals.push(this); disposeGeometry.call(this); };
const scene = new DiceScene({ prepend() {} }, () => {});
const draw = (time = performance.now()) => {
  const pending = [...callbacks.values()]; callbacks.clear();
  for (const callback of pending) callback(time);
};
scene.reset([
  { id: 'one', type: 'normal', origin: new THREE.Vector3(), position: new THREE.Vector3(0, 0.5, 0) },
  { id: 'two', type: 'devil', origin: new THREE.Vector3(), position: new THREE.Vector3(-1, 0.5, 0) },
  { id: 'three', type: 'heavenly', origin: new THREE.Vector3(), position: new THREE.Vector3(1, 0.5, 0) },
  { id: 'four', type: 'heavenly', origin: new THREE.Vector3(), position: new THREE.Vector3(2, 0.5, 0) },
  { id: 'five', type: 'monk', origin: new THREE.Vector3(), position: new THREE.Vector3(3, 0.5, 0) },
]);
scene.resize(1000, 800, 200);
draw();
assert.equal(renders, 1);
assert.equal(callbacks.size, 0, 'No continuous rendering while idle');
const destination = new THREE.Vector3(2, 0.5, 1);
const otherDestination = new THREE.Vector3(3.25, 0.5, 1);
scene.moveBatch([{ id: 'one', position: destination }, { id: 'two', position: otherDestination }], () => completions++);
draw(performance.now() + 300);
assert.ok(scene.position('one').distanceTo(destination) < 1e-9);
assert.ok(scene.position('two').distanceTo(otherDestination) < 1e-9);
assert.equal(completions, 1);
scene.setIndicators(['one', 'two'], 'one', 'B');
draw();
assert.equal(callbacks.size, 0, 'Selection feedback does not introduce continuous rendering');
scene.roll(rolls.pools[1][0], [{ id: 'one', value: 6 }], () => completions++);
scene.reset([]);
draw(performance.now() + 10000);
assert.equal(completions, 1, 'Reset cancels an active animation and its callback');
scene.animate(() => false, () => completions++);
scene.dispose();
assert.equal(callbacks.size, 0);
assert.equal(disposed, 1);
assert.equal(textureDisposals.length, 54, 'Four dice types, table cloth, golden ribbon, ribbon shadow and shared shadow release their textures');
assert.equal(new Set(textureDisposals).size, 54, 'Shared textures are disposed exactly once');
assert.equal(geometryDisposals.length, 10, 'Two shared dice shapes, shadow, four indicators, table, ribbon and ribbon shadow release their geometry');
assert.equal(new Set(geometryDisposals).size, 10, 'Shared dice geometry is disposed exactly once');
THREE.Texture.prototype.dispose = disposeTexture;
THREE.BufferGeometry.prototype.dispose = disposeGeometry;
assert.equal(removed, 1);
scene.invalidate();
assert.equal(callbacks.size, 0, 'A disposed scene cannot schedule more frames');
console.log(`Farkle state, layout, ${poses} final poses, rendering lifecycle passed.`);
