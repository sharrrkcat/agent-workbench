import { CanvasTexture, ClampToEdgeWrapping, MeshStandardMaterial, RepeatWrapping, SRGBColorSpace } from 'three';

const SIZE = 512;
const WORLD_TILE = 16;
const TAU = Math.PI * 2;

// Tavern Green Baize Felt Palette
const BASE_R = 24, BASE_G = 48, BASE_B = 34; // #183022
const HIGHLIGHT_R = 34, HIGHLIGHT_G = 66, HIGHLIGHT_B = 46; // #22422e
const SHADOW_R = 18, SHADOW_G = 36, SHADOW_B = 26; // #12241a

export const RIBBON_WIDTH = 3.1;
export const RIBBON_CENTER_Z = -0.2;
export const RIBBON_SHADOW_WIDTH = 3.42;
export const RIBBON_SHADOW_CENTER_Z = -0.11;
export const RIBBON_TILE_X = 8.0;

/** Fine tavern-green baize felt across a continuous tabletop gaming surface. */
export function tableMaterial() {
  const color = document.createElement('canvas'), height = document.createElement('canvas');
  color.width = color.height = height.width = height.height = SIZE;
  const colorContext = color.getContext('2d')!, heightContext = height.getContext('2d')!;
  const pixels = colorContext.createImageData(SIZE, SIZE), relief = heightContext.createImageData(SIZE, SIZE);

  let idx = 0;
  for (let y = 0; y < SIZE; y++) {
    const v = (y / SIZE) * TAU;
    for (let x = 0; x < SIZE; x++) {
      const u = (x / SIZE) * TAU;

      // 1. Diagonal wool twill weave
      const weave1 = Math.sin(x * 1.8) * Math.cos(y * 1.8);
      const weave2 = Math.sin((x - y) * 2.4) * 0.5;
      const weave3 = Math.cos((x + y) * 3.2) * 0.3;

      // 2. Subtle organic wool fiber mottling
      const broad1 = Math.sin(u * 2 + 0.4 * Math.sin(v)) * 0.6 + Math.cos(v * 2 - 0.3 * Math.sin(u)) * 0.4;
      const broad2 = Math.sin(u * 4 + v * 3) * 0.3 + Math.cos(u * 3 - v * 4) * 0.3;

      // 3. Fast integer hash for micro-fiber fuzz (deterministic)
      let h = Math.imul(x + y * SIZE + 101, 0x45d9f3b);
      h = Math.imul(h ^ (h >>> 16), 0x45d9f3b);
      const fuzz = (((h ^ (h >>> 16)) >>> 0) / 0xffffffff - 0.5) * 8;

      const feltTexture = weave1 * 4 + weave2 * 2.5 + weave3 * 1.5 + fuzz;
      const broad = broad1 * 0.6 + broad2 * 0.4;

      const t = broad * 0.08 + (feltTexture / 15) * 0.08;

      let r: number, g: number, b: number;
      if (t >= 0) {
        const k = Math.min(1, t / 0.16);
        r = BASE_R + k * (HIGHLIGHT_R - BASE_R);
        g = BASE_G + k * (HIGHLIGHT_G - BASE_G);
        b = BASE_B + k * (HIGHLIGHT_B - BASE_B);
      } else {
        const k = Math.min(1, -t / 0.16);
        r = BASE_R - k * (BASE_R - SHADOW_R);
        g = BASE_G - k * (BASE_G - SHADOW_G);
        b = BASE_B - k * (BASE_B - SHADOW_B);
      }

      const depth = Math.max(0, Math.min(255, 128 + feltTexture * 1.8 + broad * 8));

      pixels.data[idx] = Math.max(0, Math.min(255, r | 0));
      pixels.data[idx + 1] = Math.max(0, Math.min(255, g | 0));
      pixels.data[idx + 2] = Math.max(0, Math.min(255, b | 0));
      pixels.data[idx + 3] = 255;

      relief.data[idx] = depth | 0;
      relief.data[idx + 1] = depth | 0;
      relief.data[idx + 2] = depth | 0;
      relief.data[idx + 3] = 255;

      idx += 4;
    }
  }

  colorContext.putImageData(pixels, 0, 0);
  heightContext.putImageData(relief, 0, 0);
  const map = new CanvasTexture(color), bumpMap = new CanvasTexture(height);
  map.colorSpace = SRGBColorSpace;
  for (const texture of [map, bumpMap]) {
    texture.wrapS = texture.wrapT = RepeatWrapping;
    texture.anisotropy = 4;
  }
  return new MeshStandardMaterial({ map, bumpMap, bumpScale: 0.008, roughness: 0.88, metalness: 0 });
}

/** Antique golden silk ribbon runner with dark stitched borders, cord piping and subtle damask weave. */
export function ribbonMaterial() {
  const RIBBON_W = 512, RIBBON_H = 128;
  const color = document.createElement('canvas'), height = document.createElement('canvas');
  color.width = height.width = RIBBON_W;
  color.height = height.height = RIBBON_H;
  const colorContext = color.getContext('2d')!, heightContext = height.getContext('2d')!;
  const pixels = colorContext.createImageData(RIBBON_W, RIBBON_H), relief = heightContext.createImageData(RIBBON_W, RIBBON_H);

  let idx = 0;
  for (let y = 0; y < RIBBON_H; y++) {
    const v = y / RIBBON_H;
    const distFromEdge = Math.min(v, 1 - v);

    for (let x = 0; x < RIBBON_W; x++) {
      const u = x / RIBBON_W;

      let r = 115, g = 85, b = 25, depth = 140;

      if (distFromEdge < 0.04) {
        // Dark outer seam stitch shadow
        const dt = distFromEdge / 0.04;
        r = 36 + dt * 28;
        g = 24 + dt * 20;
        b = 4 + dt * 10;
        depth = 60 + dt * 40;
      } else if (distFromEdge < 0.10) {
        // Muted gold cord piping trim with gentle stitch highlight
        const pt = (distFromEdge - 0.04) / (0.10 - 0.04);
        const arch = Math.sin(pt * Math.PI);
        const stitch = Math.sin(u * TAU * 16) * 4;
        r = 132 + arch * 16 + stitch;
        g = 98 + arch * 14 + stitch * 0.8;
        b = 28 + arch * 10 + stitch * 0.5;
        depth = 185 + arch * 30 + stitch * 0.5;
      } else if (distFromEdge < 0.13) {
        // Inner accent groove
        r = 78; g = 56; b = 16;
        depth = 110;
      } else {
        // Darkened antique gold silk body
        const dome = Math.sin(v * Math.PI) * 8;
        const silkRib = Math.sin(y * 1.5) * 1.5;
        const damask = Math.sin((u * 4 + v * 2) * TAU) * Math.sin((u * 4 - v * 2) * TAU) * 4;
        const tone = dome + silkRib + damask;

        r = Math.min(150, Math.max(85, 115 + tone));
        g = Math.min(115, Math.max(60, 85 + tone * 0.8));
        b = Math.min(42, Math.max(14, 25 + tone * 0.5));
        depth = Math.min(200, Math.max(100, 140 + dome * 1.2 + damask * 0.5 + silkRib));
      }

      pixels.data[idx] = r | 0;
      pixels.data[idx + 1] = g | 0;
      pixels.data[idx + 2] = b | 0;
      pixels.data[idx + 3] = 255;

      relief.data[idx] = depth | 0;
      relief.data[idx + 1] = depth | 0;
      relief.data[idx + 2] = depth | 0;
      relief.data[idx + 3] = 255;

      idx += 4;
    }
  }

  colorContext.putImageData(pixels, 0, 0);
  heightContext.putImageData(relief, 0, 0);
  const map = new CanvasTexture(color), bumpMap = new CanvasTexture(height);
  map.colorSpace = SRGBColorSpace;
  for (const texture of [map, bumpMap]) {
    texture.wrapS = RepeatWrapping;
    texture.wrapT = RepeatWrapping;
    texture.anisotropy = 4;
  }
  return new MeshStandardMaterial({ map, bumpMap, bumpScale: 0.003, roughness: 0.68, metalness: 0.12 });
}

/** Soft contact and drop shadow texture cast by the golden ribbon onto the table cloth. */
export function ribbonShadowTexture() {
  const width = 32, height = 64;
  const canvas = document.createElement('canvas');
  canvas.width = width; canvas.height = height;
  const ctx = canvas.getContext('2d')!;
  const pixels = ctx.createImageData(width, height);
  for (let y = 0; y < height; y++) {
    const v = y / height;
    let alpha = 0;
    if (v < 0.02) {
      alpha = (v / 0.02) * 0.35;
    } else if (v <= 0.927) {
      alpha = 0.55;
    } else {
      const t = (v - 0.927) / (1 - 0.927);
      alpha = (1 - t) * 0.55;
    }
    const a = Math.round(alpha * 255);
    for (let x = 0; x < width; x++) {
      const idx = (y * width + x) * 4;
      pixels.data[idx] = 0;
      pixels.data[idx + 1] = 0;
      pixels.data[idx + 2] = 0;
      pixels.data[idx + 3] = a;
    }
  }
  ctx.putImageData(pixels, 0, 0);
  const texture = new CanvasTexture(canvas);
  texture.wrapS = RepeatWrapping;
  texture.wrapT = ClampToEdgeWrapping;
  return texture;
}

/** The table mesh grows to cover the camera, while felt weave stays anchored in world space. */
export function fitTableTexture(material: MeshStandardMaterial, worldSize: number) {
  const repeat = worldSize / WORLD_TILE;
  for (const texture of [material.map!, material.bumpMap!]) {
    texture.repeat.set(repeat, repeat);
    texture.offset.set((1 - repeat) / 2, (1 - repeat) / 2);
    texture.updateMatrix();
  }
}

/** The ribbon mesh spans the table in X while repeating pattern stays anchored in world space. */
export function fitRibbonTexture(material: MeshStandardMaterial, worldSize: number) {
  const repeatX = worldSize / RIBBON_TILE_X;
  for (const texture of [material.map!, material.bumpMap!]) {
    texture.repeat.set(repeatX, 1);
    texture.offset.set((1 - repeatX) / 2, 0);
    texture.updateMatrix();
  }
}
