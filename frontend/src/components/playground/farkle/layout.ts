import { MathUtils, PerspectiveCamera, Vector3 } from 'three';
import type { PlayerId } from './state';

export const ELEVATION = 85;
export const SLOT_GAP = 1.25;
const angle = MathUtils.degToRad(ELEVATION);
const sin = Math.sin(angle), cos = Math.cos(angle), tan = Math.tan(MathUtils.degToRad(12));
const THROW_X = -2.1, STORE_X = 5.25;
const side = (player: PlayerId) => player === 'A' ? -1 : 1;

export function tableLayout(width: number, height: number) {
  const aspect = width / height;
  const compact = width < 768;
  const throwCenter = compact ? 0 : THROW_X;
  const halfWidth = compact ? 4.8 : 6.9;
  // Narrow viewports frame only the throw, including room for airborne dice.
  const points: [number, number, number][] = [];
  for (const x of [-halfWidth, halfWidth]) for (const y of [0, 1.4]) for (const z of [-4.8, 4.8]) points.push([x, y, z]);
  for (const x of [throwCenter - 3, throwCenter + 3]) for (const z of [-3, 3]) points.push([x, 7.8, z]);
  let distance = 0;
  for (const [x, y, z] of points) {
    const dy = y - 0.5;
    distance = Math.max(distance, sin * dy + cos * z + Math.max(
      Math.abs(x) / (tan * aspect * 0.92), Math.abs(cos * dy - sin * z) / (tan * 0.88)));
  }
  // Keep the center line beyond either settled view without changing its zoom.
  const groundReach = (tan * distance + 0.5 * (sin * tan + cos)) / (sin - tan * cos);
  const viewOffset = groundReach + 1;
  // Retain storage's vertical position while moving both views away from the line.
  const storeZ = viewOffset - groundReach * 0.45;
  const viewWidth = 2 * distance * tan * aspect;
  const throwX = compact ? 0 : Math.min(THROW_X, -viewWidth * 0.15);
  const storeX = compact ? viewWidth / 2 + 2 + 5 * SLOT_GAP : Math.max(STORE_X, viewWidth * 0.35);
  const origins = { A: new Vector3(throwX, 0, -viewOffset), B: new Vector3(throwX, 0, viewOffset) };
  const views = { A: new Vector3(0, 0.5, -viewOffset), B: new Vector3(0, 0.5, viewOffset) };
  const slot = (player: PlayerId, row: number, column: number, count: number) => {
    const z = side(player) * (storeZ + (row - 1) * SLOT_GAP);
    return new Vector3(storeX + (0.5 - (count - 1 - column)) * SLOT_GAP, 0.5, z)
      .sub(origins[player]);
  };
  return { aspect, distance, storeZ, origins, views, slot };
}
export type TableLayout = ReturnType<typeof tableLayout>;

export function placeCamera(camera: PerspectiveCamera, layout: TableLayout, target: Vector3) {
  camera.aspect = layout.aspect;
  camera.far = Math.max(200, layout.distance * 3);
  camera.position.set(target.x, target.y + layout.distance * sin, target.z + layout.distance * cos);
  camera.up.set(0, cos, -sin);
  camera.lookAt(target);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld();
}

export function initialPosition(index: number) {
  return new Vector3((index % 3 - 1) * 1.6, 0.5, (Math.floor(index / 3) - 0.5) * 1.6);
}
