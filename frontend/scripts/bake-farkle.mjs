import RAPIER from '@dimforge/rapier3d-compat';
import { Quaternion, Vector3 } from 'three';
import { writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

// Unit dice on an open wooden table. Bounds reject throws; they are not walls.
export const RECIPE = {
  seed: 20261026, simHz: 960, sampleRate: 60, solverIterations: 8, ccdSubsteps: 4,
  contactFrequency: 240,
  halfWidth: 3.2, halfDepth: 2.5, bevelRadius: 0.08,
  spawnX: 2, spawnZ: 1.5, spawnMinY: 5.8, spawnMaxY: 6.8, staggerY: 0.15,
  gravity: -100, floorFriction: 0.68, diceFriction: 0.32,
  floorRestitution: 0.40, diceRestitution: 0.46,
  linearDamping: 0.50, angularDamping: 0.55,
  minSeconds: 0.9, maxSeconds: 1.35, quietSeconds: 0.1,
  maxPenetration: 0.02, finalSpacing: 1.4,
  counts: [32, 32, 32, 32, 32, 64],
};

function randomSource(seed) {
  let a = seed >>> 0;
  return () => {
    let t = (a += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function upComponents(q) {
  return [2 * (q.x * q.y + q.z * q.w), 1 - 2 * (q.x * q.x + q.z * q.z),
    2 * (q.y * q.z - q.x * q.w)];
}
function supportHeight(q, bevel) {
  return (0.5 - bevel) * upComponents(q).reduce((sum, v) => sum + Math.abs(v), 0) + bevel;
}

await RAPIER.init();

export function simulate(n, seed, recipe = RECIPE) {
  const random = randomSource(seed), range = (min, max) => min + random() * (max - min);
  const world = new RAPIER.World({ x: 0, y: recipe.gravity, z: 0 });
  world.timestep = 1 / recipe.simHz;
  world.integrationParameters.numSolverIterations = recipe.solverIterations;
  world.integrationParameters.maxCcdSubsteps = recipe.ccdSubsteps;
  world.integrationParameters.contact_natural_frequency = recipe.contactFrequency;
  try {
    world.createCollider(RAPIER.ColliderDesc.cuboid(20, 0.5, 20).setTranslation(0, -0.5, 0)
      .setFriction(recipe.floorFriction).setRestitution(recipe.floorRestitution));
    const bodies = [], positions = [];
    const inner = 0.5 - recipe.bevelRadius;
    const shape = new RAPIER.RoundCuboid(inner, inner, inner, recipe.bevelRadius);
    for (let i = 0; i < n; i++) {
      const u = random(), a = range(0, Math.PI * 2), b = range(0, Math.PI * 2);
      const rotation = { x: Math.sqrt(1 - u) * Math.sin(a), y: Math.sqrt(1 - u) * Math.cos(a),
        z: Math.sqrt(u) * Math.sin(b), w: Math.sqrt(u) * Math.cos(b) };
      let position;
      for (let attempt = 0; attempt < 100; attempt++) {
        const r = Math.sqrt(random()), theta = range(0, Math.PI * 2);
        const p = { x: Math.cos(theta) * r * recipe.spawnX,
          y: range(recipe.spawnMinY, recipe.spawnMaxY) + i * recipe.staggerY,
          z: Math.sin(theta) * r * recipe.spawnZ };
        // Test the oriented rounded cubes, leaving a small initial air gap.
        if (positions.every((other) => !shape.contactShape(p, rotation, shape, other.position, other.rotation, 0.04))) {
          position = p; break;
        }
      }
      if (!position) return 'spawn';
      positions.push({ position, rotation });
      const direction = Math.atan2(-position.z, -position.x) + range(-0.7, 0.7), speed = range(1, 2.6);
      const body = world.createRigidBody(RAPIER.RigidBodyDesc.dynamic()
        .setTranslation(position.x, position.y, position.z).setRotation(rotation)
        .setLinvel(Math.cos(direction) * speed, range(-3.5, -1), Math.sin(direction) * speed)
        .setAngvel({ x: range(-20, 20), y: range(-20, 20), z: range(-20, 20) })
        .setLinearDamping(recipe.linearDamping).setAngularDamping(recipe.angularDamping).setCcdEnabled(true));
      world.createCollider(RAPIER.ColliderDesc.roundCuboid(inner, inner, inner, recipe.bevelRadius)
        .setFriction(recipe.diceFriction).setRestitution(recipe.diceRestitution), body);
      bodies.push(body);
    }

    const frames = [], previous = [], stride = recipe.simHz / recipe.sampleRate;
    const record = () => frames.push(bodies.map((body, i) => {
      const p = body.translation(), r = body.rotation();
      let q = [r.x, r.y, r.z, r.w];
      if (previous[i] && q.reduce((sum, v, axis) => sum + v * previous[i][axis], 0) < 0) q = q.map((v) => -v);
      previous[i] = q;
      return [p.x, p.y, p.z, ...q].map((v) => Number(v.toFixed(5)));
    }));
    // Include t=0 and stop on a sampled step, so frame count owns duration exactly.
    record();
    let quiet = 0, finished = false;
    for (let step = 1; step <= Math.round(recipe.maxSeconds * recipe.simHz); step++) {
      world.step();
      let allQuiet = true;
      for (const body of bodies) {
        const p = body.translation(), q = body.rotation(), v = body.linvel(), w = body.angvel();
        if (Math.abs(p.x) > recipe.halfWidth || Math.abs(p.z) > recipe.halfDepth) return 'bounds';
        if (p.y - supportHeight(q, recipe.bevelRadius) < -recipe.maxPenetration) return 'penetration';
        if (Math.hypot(v.x, v.y, v.z) > 0.04 || Math.hypot(w.x, w.y, w.z) > 0.08) allQuiet = false;
      }
      quiet = allQuiet ? quiet + 1 : 0;
      if (step % stride === 0) {
        record();
        if (quiet >= recipe.quietSeconds * recipe.simHz) { finished = true; break; }
      }
    }
    if (!finished) return 'timeout';
    if ((frames.length - 1) / recipe.sampleRate < recipe.minSeconds) return 'short';
    const last = frames.at(-1);
    for (let i = 0; i < n; i++) {
      const p = last[i], q = new Quaternion(...p.slice(3)).normalize();
      if (Math.abs(p[1] - 0.5) > 0.005 || Math.max(...upComponents(q).map(Math.abs)) < 0.9999) return 'tilt';
      for (let j = 0; j < i; j++) {
        if (Math.hypot(p[0] - last[j][0], p[2] - last[j][2]) < recipe.finalSpacing) return 'spacing';
      }
    }
    // Check the actual 60 Hz lerp/slerp path, including between recorded poses.
    const poses = bodies.map(() => ({ position: new Vector3(), rotation: new Quaternion() }));
    const q1 = new Quaternion();
    for (let frame = 1; frame < frames.length; frame++) {
      for (let part = 0; part < stride; part++) {
        const alpha = part / stride;
        for (let i = 0; i < n; i++) {
          const a = frames[frame - 1][i], b = frames[frame][i], pose = poses[i];
          pose.position.set(a[0] + (b[0] - a[0]) * alpha, a[1] + (b[1] - a[1]) * alpha, a[2] + (b[2] - a[2]) * alpha);
          pose.rotation.fromArray(a, 3).normalize().slerp(q1.fromArray(b, 3).normalize(), alpha);
          if (pose.position.y - supportHeight(pose.rotation, recipe.bevelRadius) < -recipe.maxPenetration) return 'interpolation';
          for (let j = 0; j < i; j++) {
            const other = poses[j];
            const contact = shape.contactShape(pose.position, pose.rotation, shape, other.position, other.rotation, 0);
            if (contact && contact.distance < -recipe.maxPenetration) return 'collision';
          }
        }
      }
    }
    return { seed, n, sampleRate: recipe.sampleRate, frames };
  } finally { world.free(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const library = { meta: { version: 'cogita-rect-1', engine: `rapier3d-compat@${RAPIER.version()}`, recipe: RECIPE }, pools: {} };
  let seed = RECIPE.seed;
  for (let n = 1; n <= 6; n++) {
    const pool = [], rejected = {};
    let attempts = 0;
    while (pool.length < RECIPE.counts[n - 1]) {
      if (++attempts > 100000) throw new Error(`Unable to fill n=${n}: ${JSON.stringify(rejected)}`);
      const result = simulate(n, seed++);
      if (typeof result === 'string') rejected[result] = (rejected[result] ?? 0) + 1;
      else pool.push(result);
    }
    library.pools[n] = pool;
    const seconds = pool.map((t) => (t.frames.length - 1) / t.sampleRate);
    console.log(JSON.stringify({ n, count: pool.length, attempts, rejected,
      seconds: { min: Math.min(...seconds), mean: seconds.reduce((sum, t) => sum + t, 0) / seconds.length, max: Math.max(...seconds) } }));
  }
  const json = JSON.stringify(library);
  writeFileSync(new URL('../src/components/playground/farkle/rolls.json', import.meta.url), json + '\n');
  console.log(`Wrote ${Buffer.byteLength(json)} bytes of Cogita rectangular throws.`);
}
