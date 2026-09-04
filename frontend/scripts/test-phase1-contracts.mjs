import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (relative) => fs.readFileSync(path.join(root, relative), 'utf8');
const types = read('src/types.ts');
const settings = read('src/components/SettingsPage.tsx');
const pet = read('src/components/PetOverlay.tsx');
const client = read('src/api/client.ts');

// The Phase 1 UI exposes only the compact settings sections.
assert.match(settings, /export type SettingsSection = 'general' \| 'models' \| 'knowledge' \| 'worldbook' \| 'pet'/);
assert.match(settings, /\['general', 'models', 'knowledge', 'worldbook', 'pet'\]/);
for (const removed of ['agents', 'capabilities', 'intent', 'web', 'comfyui', 'image-generation']) {
  assert.doesNotMatch(settings.toLowerCase(), new RegExp(removed));
}

// Transport types contain only generic run steps and nested Pet settings.
assert.match(types, /export type RunStepKind = 'context' \| 'model' \| 'save' \| 'approval' \| 'tool'/);
assert.match(types, /export type PetSettings = \{[\s\S]*position: PetPosition;[\s\S]*bubble_texts: PetBubbleTexts/);
for (const removed of ['action_id', 'command_name', 'default_agent_id', 'available_actions']) {
  assert.doesNotMatch(types, new RegExp(removed));
}

// Pet rendering is driven by stable run status/step kinds and the façade APIs.
assert.match(pet, /step\?\.kind === 'approval'/);
assert.match(pet, /run\.status === 'WAITING_FOR_USER'/);
assert.match(pet, /api\.getPetSettings\(\)/);
assert.match(pet, /api\.listPets\(\)/);
assert.doesNotMatch(pet, /Resolving agent|Starting script/);

// The client keeps the Pet settings façade but has no old command/action calls.
assert.match(client, /getPetSettings|updatePetSettings|listPets/);
for (const removed of ['submitForm', 'actions', 'intent', 'image-generation', '/agents', '/commands']) {
  assert.doesNotMatch(client.toLowerCase(), new RegExp(removed.toLowerCase()));
}

console.log('phase1 frontend contracts: ok');
