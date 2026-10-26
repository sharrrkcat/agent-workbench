import { BufferGeometry, Float32BufferAttribute, Vector3 } from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { FACE_NORMALS } from './playback';

export function diceGeometry(shape: 'rounded' | 'roundFaces') {
  if (shape === 'rounded') return new RoundedBoxGeometry(1, 1, 1, 4, 0.08);

  // A sphere cut by the six planes at +/-0.5 gives genuinely circular faces.
  // Polar rings meet exactly at the circle and at each adjacent cube-face patch.
  const faceRadius = 0.45, radius = Math.hypot(0.5, faceRadius), sectors = 64, rings = 4;
  const geometry = new BufferGeometry();
  const positions: number[] = [], normals: number[] = [], uvs: number[] = [];
  for (const [face, normal] of FACE_NORMALS.entries()) {
    const u = normal.x ? new Vector3(0, 0, -normal.x) : new Vector3(1, 0, 0);
    const v = new Vector3().crossVectors(normal, u);
    const vertex = (point: Vector3, curved: boolean) => {
      const world = u.clone().multiplyScalar(point.x).addScaledVector(v, point.y).addScaledVector(normal, point.z);
      positions.push(...world.toArray());
      normals.push(...(curved ? world.clone().normalize() : normal).toArray());
      uvs.push(point.x + 0.5, point.y + 0.5);
    };
    const circle = (sector: number) => {
      const angle = sector / sectors * Math.PI * 2;
      return new Vector3(faceRadius * Math.cos(angle), faceRadius * Math.sin(angle), 0.5);
    };
    let start = positions.length / 3;
    for (let sector = 0; sector < sectors; sector++) {
      vertex(new Vector3(0, 0, 0.5), false); vertex(circle(sector), false); vertex(circle(sector + 1), false);
    }
    geometry.addGroup(start, positions.length / 3 - start, face);
    const surface = (sector: number, ring: number) => {
      const angle = sector / sectors * Math.PI * 2, cos = Math.cos(angle), sin = Math.sin(angle);
      const edge = 0.5 / Math.max(Math.abs(cos), Math.abs(sin));
      const distance = faceRadius + (edge - faceRadius) * ring / rings;
      return new Vector3(distance * cos, distance * sin, 0.5).normalize().multiplyScalar(radius);
    };
    start = positions.length / 3;
    for (let ring = 0; ring < rings; ring++) for (let sector = 0; sector < sectors; sector++) {
      const a = surface(sector, ring), b = surface(sector, ring + 1);
      const c = surface(sector + 1, ring + 1), d = surface(sector + 1, ring);
      for (const point of [a, b, c, a, c, d]) vertex(point, true);
    }
    geometry.addGroup(start, positions.length / 3 - start, 6);
  }
  geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
  geometry.setAttribute('normal', new Float32BufferAttribute(normals, 3));
  geometry.setAttribute('uv', new Float32BufferAttribute(uvs, 2));
  geometry.computeBoundingBox(); geometry.computeBoundingSphere();
  return geometry;
}
