import { Matrix4, Quaternion, Vector3 } from 'three';
import type { FaceValue } from './dice';

export type Trajectory = { seed: number; n: number; sampleRate: number; frames: number[][][] };
export const FACE_VALUES = [2, 5, 1, 6, 3, 4] as const;
export const FACE_NORMALS = [new Vector3(1, 0, 0), new Vector3(-1, 0, 0), new Vector3(0, 1, 0),
  new Vector3(0, -1, 0), new Vector3(0, 0, 1), new Vector3(0, 0, -1)];
const rotations: Quaternion[] = [];
for (const x of FACE_NORMALS) for (const y of FACE_NORMALS) {
  if (Math.abs(x.dot(y)) > 0.5) continue;
  rotations.push(new Quaternion().setFromRotationMatrix(new Matrix4().makeBasis(x, y, new Vector3().crossVectors(x, y))));
}

export function faceCorrection(final: Quaternion, value: FaceValue, random = Math.random) {
  const normal = FACE_NORMALS[FACE_VALUES.indexOf(value)];
  let best = -Infinity;
  let candidates: Quaternion[] = [];
  for (const rotation of rotations) {
    const up = normal.clone().applyQuaternion(final.clone().multiply(rotation)).y;
    if (up > best + 1e-5) { best = up; candidates = [rotation]; }
    else if (Math.abs(up - best) < 1e-5) candidates.push(rotation);
  }
  return candidates[Math.floor(random() * candidates.length)].clone();
}

export function shuffled<T>(values: T[], random = Math.random) {
  const result = [...values];
  for (let i = result.length - 1; i > 0; i--) {
    const j = Math.floor(random() * (i + 1));
    [result[i], result[j]] = [result[j], result[i]];
  }
  return result;
}

export function pickTrajectory(pool: Trajectory[], recent: Map<number, number[]>, random = Math.random) {
  const count = pool[0].n;
  const history = recent.get(count) ?? [];
  const candidates = pool.filter((trajectory) => !history.includes(trajectory.seed));
  const trajectory = candidates[Math.floor(random() * candidates.length)];
  history.push(trajectory.seed);
  if (history.length > 8) history.shift();
  recent.set(count, history);
  return trajectory;
}

export class RollPlayback {
  readonly tracks: { id: string; channel: number; correction: Quaternion }[];
  private yaw: Quaternion;
  private p0 = new Vector3();
  private p1 = new Vector3();
  private q0 = new Quaternion();
  private q1 = new Quaternion();
  constructor(readonly trajectory: Trajectory, dice: { id: string; value: FaceValue }[],
    readonly mirror: boolean, readonly angle: number, readonly speed: number, random = Math.random) {
    this.yaw = new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), angle);
    const channels = shuffled(dice.map((_, index) => index), random);
    this.tracks = dice.map((die, index) => {
      const channel = channels[index];
      const frame = trajectory.frames[trajectory.frames.length - 1][channel];
      const final = this.rotation(frame, new Quaternion()).premultiply(this.yaw);
      return { id: die.id, channel, correction: faceCorrection(final, die.value, random) };
    });
  }
  private rotation(frame: number[], out: Quaternion) {
    return out.set(frame[3], this.mirror ? -frame[4] : frame[4], this.mirror ? -frame[5] : frame[5], frame[6]).normalize();
  }
  sample(elapsedMs: number, write: (id: string, position: Vector3, rotation: Quaternion) => void) {
    const last = this.trajectory.frames.length - 1;
    const frame = Math.min(last, Math.max(0, elapsedMs) / 1000 * this.speed * this.trajectory.sampleRate);
    const a = Math.floor(frame), b = Math.min(last, a + 1), alpha = frame - a;
    const cos = Math.cos(this.angle), sin = Math.sin(this.angle);
    for (const track of this.tracks) {
      const f0 = this.trajectory.frames[a][track.channel], f1 = this.trajectory.frames[b][track.channel];
      this.p0.set(this.mirror ? -f0[0] : f0[0], f0[1], f0[2]);
      this.p1.set(this.mirror ? -f1[0] : f1[0], f1[1], f1[2]);
      this.p0.lerp(this.p1, alpha);
      const x = this.p0.x, z = this.p0.z;
      this.p0.set(x * cos + z * sin, this.p0.y, -x * sin + z * cos);
      this.rotation(f0, this.q0).slerp(this.rotation(f1, this.q1), alpha);
      this.q0.premultiply(this.yaw).multiply(track.correction);
      write(track.id, this.p0, this.q0);
    }
    return frame === last;
  }
}
