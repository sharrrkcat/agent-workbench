import * as THREE from 'three';
import { FACE_VALUES } from './playback';
import type { DieType } from './dice';

type Appearance = {
  body: string; pip: string; roughness: number; metalness: number; bump: number;
  surface: 'wood' | 'metal' | 'amber' | 'earth' | 'plain' | 'rust' | 'stone';
  pips: 'rings' | 'recessed' | 'small' | 'painted' | 'diamonds';
  geometry?: 'roundFaces'; border?: 'patina';
};
export const APPEARANCE: Record<DieType, Appearance> = {
  normal: { body: '#b88442', pip: '#51341b', roughness: 0.74, metalness: 0, bump: 0.09, surface: 'wood', pips: 'rings' },
  even: { body: '#a68b38', pip: '#3a3019', roughness: 0.36, metalness: 0.68, bump: 0.1, surface: 'metal', pips: 'recessed' },
  odd: { body: '#b46d46', pip: '#472a20', roughness: 0.4, metalness: 0.7, bump: 0.1, surface: 'metal', pips: 'recessed' },
  devil: { body: '#db8d25', pip: '#75421a', roughness: 0.22, metalness: 0, bump: 0.1, surface: 'amber', pips: 'recessed' },
  weighted: { body: '#927456', pip: '#181611', roughness: 0.98, metalness: 0, bump: 0.035, surface: 'earth', pips: 'small' },
  lucky: { body: '#c7dfea', pip: '#526877', roughness: 0.66, metalness: 0, bump: 0.1, surface: 'plain', pips: 'recessed' },
  unlucky: { body: '#258d59', pip: '#e7c74c', roughness: 0.65, metalness: 0, bump: 0.1, surface: 'plain', pips: 'recessed' },
  favourable: { body: '#bfc3cb', pip: '#454953', roughness: 0.32, metalness: 0.8, bump: 0.1, surface: 'metal', pips: 'recessed' },
  pie: { body: '#b87349', pip: '#593423', roughness: 0.36, metalness: 0.78, bump: 0.1, surface: 'metal', pips: 'recessed' },
  misfortune: { body: '#b5a083', pip: '#191713', roughness: 0.98, metalness: 0, bump: 0.035, surface: 'earth', pips: 'small' },
  monk: { body: '#92704c', pip: '#44392c', roughness: 0.7, metalness: 0.58, bump: 0.1, surface: 'rust', pips: 'recessed', border: 'patina' },
  strip: { body: '#b7c8e6', pip: '#585e80', roughness: 0.67, metalness: 0, bump: 0.1, surface: 'plain', pips: 'recessed' },
  unbalanced: { body: '#93948b', pip: '#303630', roughness: 0.94, metalness: 0, bump: 0.12, surface: 'stone', pips: 'recessed' },
  shrinking: { body: '#4f647b', pip: '#243445', roughness: 0.86, metalness: 0, bump: 0.1, surface: 'plain', pips: 'recessed' },
  painted: { body: '#266daf', pip: '#f4f5ee', roughness: 0.5, metalness: 0, bump: 0.015, surface: 'plain', pips: 'painted' },
  heavenly: { body: '#f0e9cc', pip: '#24221d', roughness: 0.64, metalness: 0, bump: 0.012, surface: 'plain', pips: 'painted', geometry: 'roundFaces' },
  grimy: { body: '#547d37', pip: '#e3bc40', roughness: 0.78, metalness: 0, bump: 0.1, surface: 'plain', pips: 'recessed' },
  lu: { body: '#346eaf', pip: '#d3e9f4', roughness: 0.6, metalness: 0, bump: 0.015, surface: 'plain', pips: 'painted' },
  ci: { body: '#346eaf', pip: '#d3e9f4', roughness: 0.6, metalness: 0, bump: 0.015, surface: 'plain', pips: 'painted' },
  fer: { body: '#346eaf', pip: '#d3e9f4', roughness: 0.6, metalness: 0, bump: 0.015, surface: 'plain', pips: 'painted' },
  aranka: { body: '#c3aa86', pip: '#181611', roughness: 0.98, metalness: 0, bump: 0.035, surface: 'earth', pips: 'small' },
  merchant: { body: '#252d31', pip: '#79cbbc', roughness: 0.46, metalness: 0.12, bump: 0.04, surface: 'plain', pips: 'diamonds' },
};

// Shared by the engraved face and the hover icon; no platform-specific emoji.
export const DEVIL_HEAD_PATH = 'M19 40 Q5 26 10 5 Q20 21 33 24 Q50 17 67 24 Q80 21 90 5 Q95 26 81 40 L86 52 Q81 80 50 96 Q19 80 14 52 Z M25 45 L44 53 L36 61 Z M75 45 L56 53 L64 61 Z M35 73 L50 79 L65 73 L59 85 L41 85 Z';
// Broad-ended ✠ silhouette; a shared path keeps the face and preview independent of fonts.
export const HEAVENLY_CROSS_PATH = 'M18 5 H82 Q54 17 54 46 Q83 46 95 18 V82 Q83 54 54 54 Q54 83 82 95 H18 Q46 83 46 54 Q17 54 5 82 V18 Q17 46 46 46 Q46 17 18 5 Z';

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
  const appearance = APPEARANCE[type];
  const coarse = appearance.surface === 'earth' || appearance.surface === 'stone';
  ctx.fillStyle = height ? '#b0b0b0' : appearance.body;
  ctx.fillRect(0, 0, 256, 256);
  // Deterministic texture noise must not consume the gameplay random stream.
  const noise = (n: number) => { const x = Math.sin(n * 127.1 + value * 31.7) * 43758.5453; return x - Math.floor(x); };
  const grains = coarse ? 1800 : 600;
  for (let i = 0; i < grains; i++) {
    const pale = i % 2 === 0;
    const alpha = coarse ? 0.15 : 0.05;
    ctx.fillStyle = pale ? `rgba(255,245,220,${alpha})` : `rgba(20,12,4,${alpha})`;
    const size = coarse ? 1 + noise(i + 10) * 2.5 : 1;
    ctx.fillRect(noise(i + 1) * 256, noise(i + 900) * 256, size, size);
  }
  if (appearance.surface === 'wood') {
    for (let i = -2; i < 30; i++) {
      const x = i * 10;
      ctx.strokeStyle = i % 3 ? 'rgba(73,40,13,0.16)' : 'rgba(246,200,118,0.2)';
      ctx.lineWidth = 1 + noise(i + 50) * 2;
      ctx.beginPath(); ctx.moveTo(x, 0);
      ctx.bezierCurveTo(x + 28, 70, x - 20, 155, x + 6, 256); ctx.stroke();
    }
  } else if (appearance.surface === 'amber') {
    for (let i = 0; i < 7; i++) {
      ctx.strokeStyle = i % 2 ? 'rgba(255,210,80,0.12)' : 'rgba(119,52,9,0.1)';
      ctx.lineWidth = 7 + i * 2;
      ctx.beginPath(); ctx.moveTo(-20, i * 46);
      ctx.bezierCurveTo(75, i * 26, 140, i * 66, 280, i * 35); ctx.stroke();
    }
  } else if (appearance.surface === 'metal') {
    ctx.strokeStyle = 'rgba(255,241,198,0.045)'; ctx.lineWidth = 1;
    for (let y = 2; y < 256; y += 4) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(256, y + 12); ctx.stroke(); }
  } else if (appearance.surface === 'rust' || appearance.surface === 'stone') {
    for (let i = 0; i < 100; i++) {
      ctx.fillStyle = height ? 'rgba(45,45,45,0.12)' : appearance.surface === 'rust'
        ? (i % 2 ? 'rgba(102,48,20,0.2)' : 'rgba(172,111,52,0.22)') : 'rgba(215,213,193,0.13)';
      ctx.beginPath(); ctx.ellipse(noise(i + 1) * 256, noise(i + 300) * 256,
        2 + noise(i + 90) * 12, 1 + noise(i + 40) * 5, noise(i + 70) * Math.PI, 0, Math.PI * 2); ctx.fill();
    }
  }
  if (appearance.border === 'patina') {
    ctx.strokeStyle = height ? '#737373' : '#504535'; ctx.lineWidth = 2;
    ctx.strokeRect(12, 12, 232, 232);
    for (let i = 0; i < 100; i++) {
      const along = noise(i + 100) * 256, edge = 3 + noise(i + 150) * 14;
      const x = i % 4 === 0 ? edge : i % 4 === 1 ? 256 - edge : along;
      const y = i % 4 === 2 ? edge : i % 4 === 3 ? 256 - edge : along;
      ctx.fillStyle = height ? 'rgba(70,70,70,0.2)' : 'rgba(65,119,88,0.4)';
      ctx.beginPath(); ctx.arc(x, y, 1 + noise(i + 30) * 4, 0, Math.PI * 2); ctx.fill();
    }
  }
}

function paintFace(type: DieType, value: number, height: boolean) {
  const result = canvas(), ctx = result.getContext('2d')!;
  const appearance = APPEARANCE[type];
  surface(ctx, type, value, height);
  if (type === 'heavenly' && value === 6) {
    if (!height) {
      ctx.save(); ctx.translate(58, 58); ctx.scale(1.4, 1.4);
      ctx.fillStyle = appearance.pip; ctx.fill(new Path2D(HEAVENLY_CROSS_PATH)); ctx.restore();
    }
    return result;
  }
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
    const radius = appearance.pips === 'small' ? 8 : appearance.pips === 'diamonds' ? 19 : value === 1 ? 36 : 25;
    if (appearance.pips === 'painted') {
      if (!height) { ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.fillStyle = appearance.pip; ctx.fill(); }
      continue;
    }
    if (appearance.pips === 'diamonds') {
      ctx.beginPath(); ctx.moveTo(x, y - radius); ctx.lineTo(x + radius, y);
      ctx.lineTo(x, y + radius); ctx.lineTo(x - radius, y); ctx.closePath();
      ctx.strokeStyle = height ? '#565656' : appearance.pip;
      ctx.lineWidth = 5; ctx.stroke();
      continue;
    }
    ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2);
    if (appearance.pips === 'rings') {
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
      if (!height && appearance.pips !== 'small') {
        ctx.beginPath(); ctx.arc(x, y + 1, radius, 0.15, Math.PI - 0.15);
        ctx.lineWidth = 2; ctx.strokeStyle = 'rgba(255,223,162,0.5)'; ctx.stroke();
      }
    }
  }
  return result;
}

export function faceCanvas(type: DieType, value: number) { return paintFace(type, value, false); }

export function dicePreview(type: DieType) {
  const face = faceCanvas(type, type === 'devil' ? 1 : type === 'heavenly' ? 6 : 5);
  if (APPEARANCE[type].geometry !== 'roundFaces') return face;
  const result = canvas(), ctx = result.getContext('2d')!;
  ctx.beginPath(); ctx.arc(128, 128, 115.2, 0, Math.PI * 2); ctx.clip(); ctx.drawImage(face, 0, 0);
  return result;
}

export function diceMaterials(type: DieType) {
  const appearance = APPEARANCE[type];
  const materials = FACE_VALUES.map((value) => {
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
  if (appearance.geometry === 'roundFaces') materials.push(new THREE.MeshPhysicalMaterial({
    color: appearance.body, roughness: appearance.roughness, metalness: appearance.metalness,
  }));
  return materials;
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
