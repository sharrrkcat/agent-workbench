import * as THREE from 'three';
import { FACE_VALUES } from './playback';
import type { DieType } from './dice';

type Appearance = { body: string; pip: string; roughness: number; metalness: number; bump: number };
const APPEARANCE: Record<DieType, Appearance> = {
  normal: { body: '#b88442', pip: '#51341b', roughness: 0.74, metalness: 0, bump: 0.09 },
  even: { body: '#a68b38', pip: '#3a3019', roughness: 0.36, metalness: 0.68, bump: 0.1 },
  odd: { body: '#b46d46', pip: '#472a20', roughness: 0.4, metalness: 0.7, bump: 0.1 },
  devil: { body: '#db8d25', pip: '#75421a', roughness: 0.22, metalness: 0, bump: 0.1 },
  weighted: { body: '#927456', pip: '#181611', roughness: 0.98, metalness: 0, bump: 0.035 },
  merchant: { body: '#252d31', pip: '#79cbbc', roughness: 0.46, metalness: 0.12, bump: 0.04 },
};

// Shared by the engraved face and the hover icon; no platform-specific emoji.
export const DEVIL_HEAD_PATH = 'M19 40 Q5 26 10 5 Q20 21 33 24 Q50 17 67 24 Q80 21 90 5 Q95 26 81 40 L86 52 Q81 80 50 96 Q19 80 14 52 Z M25 45 L44 53 L36 61 Z M75 45 L56 53 L64 61 Z M35 73 L50 79 L65 73 L59 85 L41 85 Z';

const coordinates: Record<number, number[][]> = {
  1: [[128, 128]], 2: [[65, 65], [191, 191]], 3: [[65, 65], [128, 128], [191, 191]],
  4: [[65, 65], [191, 65], [65, 191], [191, 191]],
  5: [[65, 65], [191, 65], [128, 128], [65, 191], [191, 191]],
  6: [[65, 59], [191, 59], [65, 128], [191, 128], [65, 197], [191, 197]],
};

function canvas() {
  const result = document.createElement('canvas');
  result.width = result.height = 256;
  return result;
}

function surface(ctx: CanvasRenderingContext2D, type: DieType, value: number, height: boolean) {
  ctx.fillStyle = height ? '#b0b0b0' : APPEARANCE[type].body;
  ctx.fillRect(0, 0, 256, 256);
  // Deterministic texture noise must not consume the gameplay random stream.
  const noise = (n: number) => { const x = Math.sin(n * 127.1 + value * 31.7) * 43758.5453; return x - Math.floor(x); };
  const grains = type === 'weighted' ? 1800 : 600;
  for (let i = 0; i < grains; i++) {
    const pale = i % 2 === 0;
    const alpha = type === 'weighted' ? 0.15 : 0.05;
    ctx.fillStyle = pale ? `rgba(255,245,220,${alpha})` : `rgba(20,12,4,${alpha})`;
    const size = type === 'weighted' ? 1 + noise(i + 10) * 2.5 : 1;
    ctx.fillRect(noise(i + 1) * 256, noise(i + 900) * 256, size, size);
  }
  if (type === 'normal') {
    for (let i = -2; i < 30; i++) {
      const x = i * 10;
      ctx.strokeStyle = i % 3 ? 'rgba(73,40,13,0.16)' : 'rgba(246,200,118,0.2)';
      ctx.lineWidth = 1 + noise(i + 50) * 2;
      ctx.beginPath(); ctx.moveTo(x, 0);
      ctx.bezierCurveTo(x + 28, 70, x - 20, 155, x + 6, 256); ctx.stroke();
    }
  } else if (type === 'devil') {
    for (let i = 0; i < 7; i++) {
      ctx.strokeStyle = i % 2 ? 'rgba(255,210,80,0.12)' : 'rgba(119,52,9,0.1)';
      ctx.lineWidth = 7 + i * 2;
      ctx.beginPath(); ctx.moveTo(-20, i * 46);
      ctx.bezierCurveTo(75, i * 26, 140, i * 66, 280, i * 35); ctx.stroke();
    }
  } else if (type === 'even' || type === 'odd') {
    ctx.strokeStyle = 'rgba(255,241,198,0.045)'; ctx.lineWidth = 1;
    for (let y = 2; y < 256; y += 4) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(256, y + 12); ctx.stroke(); }
  }
}

function paintFace(type: DieType, value: number, height: boolean) {
  const result = canvas(), ctx = result.getContext('2d')!;
  const appearance = APPEARANCE[type];
  surface(ctx, type, value, height);
  if (type === 'devil' && value === 1) {
    ctx.save(); ctx.translate(59, 57); ctx.scale(1.38, 1.38);
    const path = new Path2D(DEVIL_HEAD_PATH);
    if (!height) {
      ctx.translate(0, 1.5); ctx.strokeStyle = 'rgba(255,221,132,0.7)'; ctx.lineWidth = 2; ctx.stroke(path);
      ctx.translate(0, -1.5);
    }
    ctx.fillStyle = height ? '#3b3b3b' : appearance.pip;
    ctx.fill(path, 'evenodd'); ctx.restore();
    return result;
  }
  for (const [x, y] of coordinates[value]) {
    const radius = type === 'weighted' ? 8 : type === 'merchant' ? 19 : value === 1 ? 36 : 25;
    if (type === 'merchant') {
      ctx.beginPath(); ctx.moveTo(x, y - radius); ctx.lineTo(x + radius, y);
      ctx.lineTo(x, y + radius); ctx.lineTo(x - radius, y); ctx.closePath();
      ctx.strokeStyle = height ? '#565656' : appearance.pip;
      ctx.lineWidth = 5; ctx.stroke();
      continue;
    }
    ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2);
    if (type === 'normal') {
      ctx.lineWidth = 9;
      ctx.strokeStyle = height ? '#3b3b3b' : appearance.pip;
      ctx.stroke();
      if (!height) {
        ctx.beginPath(); ctx.arc(x, y + 1.5, radius + 5, 0.1, Math.PI - 0.1);
        ctx.lineWidth = 2; ctx.strokeStyle = '#d8ab68'; ctx.stroke();
        ctx.beginPath(); ctx.arc(x, y, radius - 5, Math.PI + 0.1, Math.PI * 2 - 0.1);
        ctx.stroke();
      }
    } else {
      const gradient = ctx.createRadialGradient(x, y - radius * 0.25, radius * 0.2, x, y, radius);
      gradient.addColorStop(0, height ? '#303030' : appearance.pip);
      gradient.addColorStop(0.8, height ? '#555555' : appearance.pip);
      gradient.addColorStop(1, height ? '#999999' : appearance.body);
      ctx.fillStyle = gradient; ctx.fill();
      if (!height && type !== 'weighted') {
        ctx.beginPath(); ctx.arc(x, y + 1, radius, 0.15, Math.PI - 0.15);
        ctx.lineWidth = 2; ctx.strokeStyle = 'rgba(255,223,162,0.5)'; ctx.stroke();
      }
    }
  }
  return result;
}

export function faceCanvas(type: DieType, value: number) { return paintFace(type, value, false); }

export function diceMaterials(type: DieType) {
  const appearance = APPEARANCE[type];
  return FACE_VALUES.map((value) => {
    const map = new THREE.CanvasTexture(faceCanvas(type, value));
    map.colorSpace = THREE.SRGBColorSpace; map.anisotropy = 4;
    const bumpMap = new THREE.CanvasTexture(paintFace(type, value, true));
    bumpMap.anisotropy = 4;
    return new THREE.MeshPhysicalMaterial({
      map, bumpMap, bumpScale: appearance.bump, roughness: appearance.roughness, metalness: appearance.metalness,
      clearcoat: type === 'devil' ? 0.85 : type === 'merchant' ? 0.25 : 0,
      clearcoatRoughness: type === 'devil' ? 0.15 : 0.4,
    });
  });
}

export function shadowTexture() {
  const result = canvas();
  result.width = result.height = 128;
  const ctx = result.getContext('2d')!;
  const gradient = ctx.createRadialGradient(64, 64, 16, 64, 64, 60);
  gradient.addColorStop(0, 'rgba(0,0,0,0.92)');
  gradient.addColorStop(0.55, 'rgba(0,0,0,0.55)');
  gradient.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = gradient; ctx.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(result);
}
