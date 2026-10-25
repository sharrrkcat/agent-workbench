import * as THREE from 'three';
import { FACE_VALUES } from './playback';
import type { SkinId } from './state';
type DiceSkin = { id: SkinId; bg: string; border: string; pipColor: string; oneColor: string; specialOne: string | null; roughness: number };

export const DICE_SKINS: DiceSkin[] = [
  {
    id: 'bone',
    bg: '#ebe3d2',
    border: '#cbbba0',
    pipColor: '#1f1a17',
    oneColor: '#b82921',
    specialOne: null,
    roughness: 0.45,
  },
  {
    id: 'devil',
    bg: '#382218',
    border: '#24140d',
    pipColor: '#e2b259',
    oneColor: '#ff4938',
    specialOne: 'DEVIL',
    roughness: 0.38,
  },
  {
    id: 'heavenly',
    bg: '#1c2b45',
    border: '#d4af37',
    pipColor: '#f3cf65',
    oneColor: '#ffffff',
    specialOne: 'CROWN',
    roughness: 0.30,
  },
  {
    id: 'painted',
    bg: '#6e1d1b',
    border: '#4a1110',
    pipColor: '#f4e2b8',
    oneColor: '#ffd447',
    specialOne: 'RING',
    roughness: 0.42,
  },
  {
    id: 'lu_odd',
    bg: '#1d1d20',
    border: '#34343a',
    pipColor: '#d0d7de',
    oneColor: '#58a6ff',
    specialOne: null,
    roughness: 0.28,
  },
  {
    id: 'tooth',
    bg: '#d9c398',
    border: '#ad9468',
    pipColor: '#3b2d1d',
    oneColor: '#8c2d19',
    specialOne: null,
    roughness: 0.58,
  },
];

export function faceCanvas(skin: DiceSkin, val: number) {
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 256;
  const ctx = canvas.getContext('2d')!;

  ctx.fillStyle = skin.bg;
  ctx.fillRect(0, 0, 256, 256);
  ctx.strokeStyle = skin.border;
  ctx.lineWidth = 18;
  ctx.strokeRect(9, 9, 238, 238);

  const grad = ctx.createRadialGradient(128, 128, 50, 128, 128, 160);
  grad.addColorStop(0, 'rgba(255,255,255,0.04)');
  grad.addColorStop(1, 'rgba(0,0,0,0.22)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 256, 256);

  const drawPip = (cx: number, cy: number, r: number) => {
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fill();

    ctx.strokeStyle = 'rgba(0,0,0,0.35)';
    ctx.lineWidth = 3;
    ctx.stroke();
  };

  if (val === 1 && skin.specialOne === 'DEVIL') {

    ctx.fillStyle = skin.oneColor;
    ctx.font = 'bold 115px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('😈', 128, 134);
  } else if (val === 1 && skin.specialOne === 'CROWN') {

    ctx.strokeStyle = skin.pipColor;
    ctx.lineWidth = 8;
    ctx.strokeRect(68, 68, 120, 120);
    ctx.fillStyle = skin.oneColor;
    ctx.font = 'bold 95px serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('✠', 128, 132);
  } else {
    ctx.fillStyle = val === 1 ? skin.oneColor : skin.pipColor;
    const R = val === 1 ? 34 : 22;
    const L = 68, C = 128, H = 188;
    const allCoords: Record<number, number[][]> = {
      1: [[C, C]],
      2: [[L, L], [H, H]],
      3: [[L, L], [C, C], [H, H]],
      4: [[L, L], [H, L], [L, H], [H, H]],
      5: [[L, L], [H, L], [C, C], [L, H], [H, H]],
      6: [[L, L], [H, L], [L, C], [H, C], [L, H], [H, H]],
    };
    const coords = allCoords[val];

    for (const [x, y] of coords) {
      drawPip(x, y, R);
      if (skin.specialOne === 'RING') {
        ctx.strokeStyle = skin.oneColor;
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(x, y, R + 7, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
  }

  return canvas;
}

export function skinMaterials(skin: DiceSkin) {
  return FACE_VALUES.map((value) => {
    const map = new THREE.CanvasTexture(faceCanvas(skin, value));
    map.colorSpace = THREE.SRGBColorSpace;
    map.anisotropy = 4;
    return new THREE.MeshStandardMaterial({ map, roughness: skin.roughness, metalness: 0.08 });
  });
}

export function shadowTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 128;
  const ctx = canvas.getContext('2d')!;
  const gradient = ctx.createRadialGradient(64, 64, 16, 64, 64, 60);
  gradient.addColorStop(0, 'rgba(0,0,0,0.92)');
  gradient.addColorStop(0.55, 'rgba(0,0,0,0.55)');
  gradient.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(canvas);
}
