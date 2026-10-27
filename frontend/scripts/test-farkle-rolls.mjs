import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import RAPIER from '@dimforge/rapier3d-compat';
import { Matrix4, Quaternion, Vector3 } from 'three';
import { RECIPE, simulate } from './bake-farkle.mjs';
import { createModuleLoader } from './module-loader.mjs';

const rolls = JSON.parse(readFileSync(new URL('../src/components/playground/farkle/rolls.json', import.meta.url)));
const { RollPlayback, pickTrajectory } = (await createModuleLoader()('../src/components/playground/farkle/playback.ts')).exports;
assert.equal(rolls.meta.version, 'cogita-rect-1');
assert.equal(rolls.meta.engine, `rapier3d-compat@${RAPIER.version()}`);
assert.deepEqual(rolls.meta.recipe, RECIPE);
const shape = new RAPIER.RoundCuboid(0.42, 0.42, 0.42, 0.08);
const matrix = new Matrix4();
const support = (q) => {
  const m = matrix.makeRotationFromQuaternion(q).elements;
  return 0.42 * (Math.abs(m[1]) + Math.abs(m[5]) + Math.abs(m[9])) + 0.08;
};
let total = 0, minimumHeight = Infinity, minimumContact = 0;
for (const [count, pool] of Object.entries(rolls.pools)) {
  const n = Number(count);
  assert.equal(pool.length, RECIPE.counts[n - 1]);
  assert.equal(new Set(pool.map((t) => t.seed)).size, pool.length);
  // Reproduce one accepted seed per count, including its unsampled physics checks.
  assert.ok(JSON.stringify(simulate(n, pool[0].seed)) === JSON.stringify(pool[0]), `Reproduce the JSON artifact for ${n} dice`);
  for (const trajectory of pool) {
    total++;
    assert.equal(trajectory.n, n);
    assert.equal(trajectory.sampleRate, 60);
    const seconds = (trajectory.frames.length - 1) / trajectory.sampleRate;
    assert.ok(seconds >= 0.9 && seconds <= 1.35);
    for (const [i, frame] of trajectory.frames.entries()) {
      assert.equal(frame.length, n);
      for (const [channel, pose] of frame.entries()) {
        assert.equal(pose.length, 7);
        assert.ok(pose.every(Number.isFinite));
        const q = new Quaternion(...pose.slice(3));
        assert.ok(Math.abs(q.length() - 1) < 0.00002);
        if (i) assert.ok(q.dot(new Quaternion(...trajectory.frames[i - 1][channel].slice(3))) > 0);
        else assert.ok(pose[1] >= 5.8 + channel * 0.15 && pose[1] <= 6.8 + channel * 0.15);
      }
    }
    const final = trajectory.frames.at(-1);
    for (let i = 0; i < n; i++) {
      assert.ok(Math.abs(final[i][1] - 0.5) < 0.005);
      for (let j = 0; j < i; j++) assert.ok(Math.hypot(final[i][0] - final[j][0], final[i][2] - final[j][2]) >= 1.4);
      const prior = trajectory.frames.at(-7)[i];
      assert.ok(new Vector3(...final[i]).distanceTo(new Vector3(...prior)) < 0.01, 'The last 100ms is settled');
    }
    const playback = new RollPlayback(trajectory, Array.from({ length: n }, (_, i) => ({ id: String(i), value: i + 1 })), true, Math.PI, 1, () => 0.4);
    const poses = Array.from({ length: n }, () => ({ p: new Vector3(), q: new Quaternion() }));
    // Exercise the actual interpolating player at 240Hz, including face correction.
    for (let sample = 0; sample <= Math.round(seconds * 240); sample++) {
      playback.sample(sample / 240 * 1000, (id, p, q) => {
        assert.ok(Math.abs(p.x) <= 3.20001 && Math.abs(p.z) <= 2.50001);
        minimumHeight = Math.min(minimumHeight, p.y - support(q));
        assert.ok(p.y - support(q) >= -0.02, `Floor contact: ${trajectory.seed}`);
        poses[Number(id)].p.copy(p); poses[Number(id)].q.copy(q);
      });
      for (let i = 0; i < n; i++) for (let j = 0; j < i; j++) {
        const a = poses[i], b = poses[j];
        const contact = shape.contactShape(a.p, a.q, shape, b.p, b.q, 0);
        if (contact) {
          minimumContact = Math.min(minimumContact, contact.distance);
          assert.ok(contact.distance >= -0.02, `Dice contact: ${trajectory.seed}`);
        }
      }
    }
  }
}
const recent = new Map(), seen = { 1: [], 6: [] };
for (let i = 0; i < 40; i++) for (const n of [1, 6]) {
  const trajectory = pickTrajectory(rolls.pools[n], recent, () => 0);
  assert.ok(!seen[n].slice(-8).includes(trajectory.seed), 'Other dice counts cannot evict recent trajectories');
  seen[n].push(trajectory.seed);
}
console.log(`Farkle: ${total} rectangular throws, reproducible seeds, floor ${minimumHeight.toFixed(5)}, dice contact ${minimumContact.toFixed(5)} passed.`);
