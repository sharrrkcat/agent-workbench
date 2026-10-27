import * as THREE from 'three';
import { APPEARANCE, shadowTexture, diceMaterials } from './materials';
import { diceGeometry } from './geometry';
import { fitRibbonTexture, fitTableTexture, ribbonMaterial, ribbonShadowTexture, RIBBON_CENTER_Z, RIBBON_SHADOW_CENTER_Z, RIBBON_SHADOW_WIDTH, RIBBON_WIDTH, tableMaterial } from './tableMaterial';
import { RollPlayback, type Trajectory } from './playback';
import type { PlayerId } from './state';
import type { DieType, FaceValue } from './dice';

type DieView = {
  root: THREE.Group; mesh: THREE.Mesh; shadow: THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>;
  hover: THREE.Mesh; selected: THREE.Mesh;
};
export type HitBounds = {
  id: string; left: number; top: number; width: number; height: number;
  centerX: number; centerY: number; iconX: number; iconY: number;
};

// Presentation only: callers supply participants, target faces, anchors and destinations.
export class DiceScene {
  readonly camera = new THREE.PerspectiveCamera(24, 1, 0.1, 200);
  private scene = new THREE.Scene();
  private renderer: THREE.WebGLRenderer;
  private geometries = new Map<'rounded' | 'roundFaces', THREE.BufferGeometry>();
  private shadowGeometry = new THREE.PlaneGeometry(1.35, 1.35).rotateX(-Math.PI / 2);
  private shadowMap = shadowTexture();
  private hoverGeometry = new THREE.RingGeometry(0.82, 0.90, 64).rotateX(-Math.PI / 2);
  private selectedGeometry = new THREE.RingGeometry(0.82, 0.90, 64, 1, Math.PI, Math.PI).rotateX(-Math.PI / 2);
  private hoverOutlineGeometry = new THREE.RingGeometry(0.80, 0.92, 64).rotateX(-Math.PI / 2);
  private selectedOutlineGeometry = new THREE.RingGeometry(0.80, 0.92, 64, 1, Math.PI - 0.023, Math.PI + 0.046).rotateX(-Math.PI / 2);
  private outlineMaterial = new THREE.MeshBasicMaterial({ color: '#000000', depthWrite: false });
  private hoverMaterial = new THREE.MeshBasicMaterial({ color: '#f3d36a', depthWrite: false });
  private selectedMaterial = new THREE.MeshBasicMaterial({ color: '#10b9f0', depthWrite: false });
  private materials = new Map<DieType, THREE.MeshStandardMaterial[]>();
  private dice = new Map<string, DieView>();
  private tableMaterial = tableMaterial();
  private ribbonMaterial = ribbonMaterial();
  private ribbonShadowMap = ribbonShadowTexture();
  private ribbonShadowGeometry = new THREE.PlaneGeometry(1, RIBBON_SHADOW_WIDTH).rotateX(-Math.PI / 2);
  private ribbonShadow = new THREE.Mesh(this.ribbonShadowGeometry, new THREE.MeshBasicMaterial({
    map: this.ribbonShadowMap, transparent: true, depthWrite: false,
  }));
  private table = new THREE.Mesh(new THREE.BoxGeometry(1, 0.3, 1), this.tableMaterial);
  private ribbon = new THREE.Mesh(new THREE.BoxGeometry(1, 0.008, RIBBON_WIDTH), this.ribbonMaterial);
  private frame = 0;
  private disposed = false;
  private width = 1;
  private height = 1;
  private animation: { start: number; update: (elapsed: number) => boolean; complete: () => void } | null = null;

  constructor(container: HTMLElement, private onBounds: (bounds: HitBounds) => void) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.domElement.setAttribute('aria-hidden', 'true');
    container.prepend(this.renderer.domElement);
    this.scene.background = new THREE.Color('#12241a');
    this.scene.add(new THREE.AmbientLight('#eef5ee', 1.35));
    const light = new THREE.DirectionalLight('#fff8ee', 1.9);
    light.position.set(-4, 15, -5);
    this.scene.add(light);
    this.table.position.y = -0.15;
    this.ribbonShadow.position.set(0, 0.002, RIBBON_SHADOW_CENTER_Z);
    this.ribbon.position.set(0, 0.004, RIBBON_CENTER_Z);
    this.scene.add(this.table, this.ribbonShadow, this.ribbon);
  }

  resize(width: number, height: number, tableSize: number) {
    this.width = width; this.height = height;
    this.renderer.setSize(width, height);
    this.table.scale.set(tableSize, 1, tableSize);
    fitTableTexture(this.tableMaterial, tableSize);
    this.ribbonShadow.scale.set(tableSize, 1, 1);
    this.ribbon.scale.set(tableSize, 1, 1);
    fitRibbonTexture(this.ribbonMaterial, tableSize);
    this.invalidate();
  }

  reset(dice: { id: string; type: DieType; origin: THREE.Vector3; position: THREE.Vector3 }[]) {
    this.cancel();
    for (const die of this.dice.values()) {
      this.scene.remove(die.root);
      die.shadow.material.dispose();
    }
    this.dice.clear();
    for (const definition of dice) {
      let material = this.materials.get(definition.type);
      if (!material) {
        material = diceMaterials(definition.type);
        this.materials.set(definition.type, material);
      }
      const root = new THREE.Group();
      root.position.copy(definition.origin);
      const shape = APPEARANCE[definition.type].geometry ?? 'rounded';
      let geometry = this.geometries.get(shape);
      if (!geometry) { geometry = diceGeometry(shape); this.geometries.set(shape, geometry); }
      const mesh = new THREE.Mesh(geometry, material);
      mesh.position.copy(definition.position);
      const shadow = new THREE.Mesh(this.shadowGeometry, new THREE.MeshBasicMaterial({
        map: this.shadowMap, transparent: true, depthWrite: false, opacity: 0.75,
      }));
      const hover = new THREE.Mesh(this.hoverGeometry, this.hoverMaterial);
      const selected = new THREE.Mesh(this.selectedGeometry, this.selectedMaterial);
      const hoverOutline = new THREE.Mesh(this.hoverOutlineGeometry, this.outlineMaterial);
      const selectedOutline = new THREE.Mesh(this.selectedOutlineGeometry, this.outlineMaterial);
      hover.add(hoverOutline);
      selected.add(selectedOutline);
      hover.visible = false; selected.visible = false;
      hoverOutline.renderOrder = 1; hover.renderOrder = 2;
      selectedOutline.renderOrder = 3; selected.renderOrder = 4;
      root.add(mesh, shadow, hover, selected);
      this.scene.add(root);
      this.dice.set(definition.id, { root, mesh, shadow, hover, selected });
    }
    this.invalidate();
  }

  setOrigin(id: string, position: THREE.Vector3) { this.dice.get(id)!.root.position.copy(position); }
  setPosition(id: string, position: THREE.Vector3) { this.dice.get(id)!.mesh.position.copy(position); }
  position(id: string) { return this.dice.get(id)!.mesh.position.clone(); }

  setIndicators(selectedIds: string[], hoverId: string | null, player: PlayerId) {
    this.selectedMaterial.color.set(player === 'A' ? '#c66a22' : '#10b9f0');
    for (const [id, die] of this.dice) {
      die.hover.visible = id === hoverId;
      die.selected.visible = selectedIds.includes(id);
    }
    this.invalidate();
  }

  animate(update: (elapsed: number) => boolean, complete: () => void) {
    this.animation = { start: performance.now(), update, complete };
    this.invalidate();
  }

  roll(trajectory: Trajectory, dice: { id: string; value: FaceValue }[], complete: () => void) {
    const playback = new RollPlayback(trajectory, dice, Math.random() < 0.5, Math.random() < 0.5 ? 0 : Math.PI,
      0.94 + Math.random() * 0.12);
    this.animate((elapsed) => playback.sample(elapsed, (id, position, rotation) => {
      const { mesh } = this.dice.get(id)!;
      mesh.position.copy(position);
      mesh.quaternion.copy(rotation);
    }), complete);
  }

  moveBatch(destinations: { id: string; position: THREE.Vector3 }[], complete: () => void) {
    const moves = destinations.map(({ id, position }) => ({ mesh: this.dice.get(id)!.mesh,
      start: this.position(id), destination: position }));
    this.animate((elapsed) => {
      const u = Math.min(1, elapsed / 280), smooth = u * u * (3 - 2 * u);
      for (const { mesh, start, destination } of moves) {
        mesh.position.lerpVectors(start, destination, smooth);
        mesh.position.y += Math.sin(u * Math.PI) * 1.6;
      }
      return u === 1;
    }, complete);
  }

  cancel() { this.animation = null; }
  invalidate = () => {
    if (!this.frame && !this.disposed) this.frame = requestAnimationFrame(this.draw);
  };

  private draw = (now: number) => {
    this.frame = 0;
    const animation = this.animation;
    if (animation && animation.update(Math.max(0, now - animation.start))) {
      this.animation = null;
      animation.complete();
    }
    for (const { mesh, shadow, hover, selected } of this.dice.values()) {
      const h = Math.max(0, mesh.position.y - 0.5);
      shadow.position.set(mesh.position.x + h * 0.12, 0.003, mesh.position.z + h * 0.12);
      shadow.scale.set(1 + h * 0.16, 1, 1 + h * 0.16);
      shadow.material.opacity = 0.78 * Math.exp(-0.36 * h);
      hover.position.set(mesh.position.x, 0.016, mesh.position.z);
      selected.position.set(mesh.position.x, 0.019, mesh.position.z);
    }
    this.renderer.render(this.scene, this.camera);
    const corner = new THREE.Vector3();
    for (const [id, { mesh, root }] of this.dice) {
      let left = Infinity, right = -Infinity, top = Infinity, bottom = -Infinity;
      for (const x of [-0.5, 0.5]) for (const y of [-0.5, 0.5]) for (const z of [-0.5, 0.5]) {
        corner.set(x, y, z).applyMatrix4(mesh.matrixWorld).project(this.camera);
        const sx = (corner.x + 1) * this.width / 2, sy = (1 - corner.y) * this.height / 2;
        left = Math.min(left, sx); right = Math.max(right, sx);
        top = Math.min(top, sy); bottom = Math.max(bottom, sy);
      }
      corner.copy(mesh.position).add(root.position).project(this.camera);
      const centerX = (corner.x + 1) * this.width / 2, centerY = (1 - corner.y) * this.height / 2;
      corner.set(mesh.position.x, 0.02, mesh.position.z + 1.18).add(root.position).project(this.camera);
      this.onBounds({ id, left, top, width: right - left, height: bottom - top, centerX, centerY,
        iconX: (corner.x + 1) * this.width / 2, iconY: (1 - corner.y) * this.height / 2 });
    }
    if (this.animation) this.invalidate();
  };

  dispose() {
    this.disposed = true;
    this.cancel();
    cancelAnimationFrame(this.frame);
    for (const die of this.dice.values()) die.shadow.material.dispose();
    for (const material of this.materials.values()) for (const face of material) {
      face.map?.dispose(); face.bumpMap?.dispose(); face.dispose();
    }
    this.materials.clear(); this.dice.clear();
    for (const geometry of this.geometries.values()) geometry.dispose();
    this.geometries.clear(); this.shadowGeometry.dispose(); this.shadowMap.dispose();
    this.hoverGeometry.dispose(); this.selectedGeometry.dispose();
    this.hoverOutlineGeometry.dispose(); this.selectedOutlineGeometry.dispose(); this.outlineMaterial.dispose();
    this.hoverMaterial.dispose(); this.selectedMaterial.dispose();
    this.table.geometry.dispose(); this.tableMaterial.map!.dispose(); this.tableMaterial.bumpMap!.dispose(); this.tableMaterial.dispose();
    this.ribbon.geometry.dispose(); this.ribbonMaterial.map!.dispose(); this.ribbonMaterial.bumpMap!.dispose(); this.ribbonMaterial.dispose();
    this.ribbonShadowGeometry.dispose(); this.ribbonShadowMap.dispose(); this.ribbonShadow.material.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
