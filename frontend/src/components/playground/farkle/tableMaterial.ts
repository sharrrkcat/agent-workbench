import { CanvasTexture, MeshStandardMaterial, RepeatWrapping, SRGBColorSpace } from 'three';

const SIZE = 1024;
const WORLD_TILE = 16;
const TAU = Math.PI * 2;

/** Periodic grain across a continuous, finely finished wooden surface. */
export function tableMaterial() {
  const color = document.createElement('canvas'), height = document.createElement('canvas');
  color.width = color.height = height.width = height.height = SIZE;
  const colorContext = color.getContext('2d')!, heightContext = height.getContext('2d')!;
  const pixels = colorContext.createImageData(SIZE, SIZE), relief = heightContext.createImageData(SIZE, SIZE);
  for (let y = 0; y < SIZE; y++) for (let x = 0; x < SIZE; x++) {
    const u = x / SIZE * TAU, v = y / SIZE * TAU;
    const warp = 0.7 * Math.sin(u + 0.25 * Math.sin(v)) + 0.22 * Math.sin(2 * u + v) + 0.1 * Math.sin(3 * u - 2 * v);
    const growth = v * 18 + warp;
    const broad = Math.sin(3 * v + 0.6 * Math.sin(u)) * 0.65 + Math.sin(7 * v + warp) * 0.35;
    const grain = Math.sin(growth + 0.35 * Math.sin(2 * growth));
    const pores = Math.max(0, Math.sin(growth * 5 + 0.45 * Math.sin(u * 4))) ** 12;
    // Integer noise supplies pores without advancing the dice/reward random stream.
    let hash = Math.imul(x + y * SIZE + 193, 0x45d9f3b);
    hash = Math.imul(hash ^ (hash >>> 16), 0x45d9f3b);
    const micro = ((hash ^ (hash >>> 16)) >>> 0) / 0xffffffff - 0.5;
    const tone = broad * 9 + grain * 3 - pores * 5 + micro * 2;
    const index = (y * SIZE + x) * 4;
    pixels.data[index] = 88 + tone;
    pixels.data[index + 1] = 58 + tone * 0.72;
    pixels.data[index + 2] = 36 + tone * 0.48;
    pixels.data[index + 3] = 255;
    const depth = 144 + grain * 12 - pores * 20 + micro * 5;
    relief.data[index] = relief.data[index + 1] = relief.data[index + 2] = depth;
    relief.data[index + 3] = 255;
  }
  colorContext.putImageData(pixels, 0, 0); heightContext.putImageData(relief, 0, 0);
  const map = new CanvasTexture(color), bumpMap = new CanvasTexture(height);
  map.colorSpace = SRGBColorSpace;
  for (const texture of [map, bumpMap]) {
    texture.wrapS = texture.wrapT = RepeatWrapping;
    texture.anisotropy = 4;
  }
  return new MeshStandardMaterial({ map, bumpMap, bumpScale: 0.018, roughness: 0.72, metalness: 0 });
}

/** The table mesh grows to cover the camera, while grain stays anchored in world space. */
export function fitTableTexture(material: MeshStandardMaterial, worldSize: number) {
  const repeat = worldSize / WORLD_TILE;
  for (const texture of [material.map!, material.bumpMap!]) {
    texture.repeat.set(repeat, repeat);
    texture.offset.set((1 - repeat) / 2, (1 - repeat) / 2);
    texture.updateMatrix();
  }
}
