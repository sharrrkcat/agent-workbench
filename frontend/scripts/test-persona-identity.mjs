import assert from 'node:assert/strict';
import fs from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import i18next from 'i18next';
import { apiMocks, createModuleLoader, mockModule, sourceUrl } from './module-loader.mjs';

const api = {};
const load = createModuleLoader(apiMocks(api));
const { usePersonasStore: personas } = (await load('../src/store/usePersonasStore.ts')).exports;
const { useCogitaStore: chat } = (await load('../src/store/useCogitaStore.ts')).exports;
const first = { id: 'first', collection: 'agent', name: 'First', avatar_attachment_id: 'first.png' };
const second = { id: 'second', collection: 'agent', name: 'Second', avatar_attachment_id: null };
const event = (type, payload) => chat.getState().applyRuntimeEvent({ type, session_id: 'session', payload });
function deferred() {
  let resolve, reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

const pending = deferred();
api.listPersonas = () => pending.promise;
const initial = personas.getState().reload();
assert.equal(personas.getState().loaded, false);
event('persona_updated', { persona: { ...first, name: 'Renamed', avatar_attachment_id: 'latest.png' } });
event('persona_deleted', { persona_id: second.id });
pending.resolve([first, second]);
await initial;
assert.deepEqual(personas.getState().personas, [{ ...first, name: 'Renamed', avatar_attachment_id: 'latest.png' }]);
assert.equal(personas.getState().loaded, true);

// A newer list request supersedes the old one; events still win over the newer list.
const old = deferred(), newer = deferred();
api.listPersonas = () => old.promise;
const oldRead = personas.getState().reload();
api.listPersonas = () => newer.promise;
const newRead = personas.getState().reload();
event('persona_updated', { persona: { ...first, name: 'Final', avatar_attachment_id: null } });
old.resolve([first]);
await oldRead;
assert.equal(personas.getState().loading, true);
newer.resolve([first, second]);
await newRead;
assert.equal(personas.getState().personas.find((item) => item.id === first.id).name, 'Final');
assert.equal(personas.getState().personas.find((item) => item.id === first.id).avatar_attachment_id, null);

const i18n = i18next.createInstance();
const resources = Object.fromEntries(['en', 'zh-CN'].map((locale) => [locale, { personas:
  JSON.parse(fs.readFileSync(new URL(`../src/i18n/resources/${locale}/personas.json`, import.meta.url), 'utf8')),
}]));
await i18n.init({ resources, lng: 'en', fallbackLng: 'en' });
const views = createModuleLoader({
  'react-i18next': mockModule({ useTranslation: (namespace) => ({ t: i18n.getFixedT(null, namespace) }) }),
  [sourceUrl('store/usePersonasStore.ts')]: mockModule({ usePersonasStore: () => personas.getState() }),
});
const { usePersonaIdentity } = (await views('../src/hooks/usePersonaIdentity.ts')).exports;
function Identity({ id }) {
  const identity = usePersonaIdentity()(id);
  return React.createElement('span', { 'data-avatar': identity.avatar_attachment_id }, identity.name);
}
const render = (id) => renderToStaticMarkup(React.createElement(Identity, { id }));
for (const locale of ['en', 'zh-CN']) {
  await i18n.changeLanguage(locale);
  assert.match(render(first.id), /Final/);
  assert.doesNotMatch(render(first.id), /first.png|latest.png/);
  assert.match(render(second.id), /Second/);
  event('persona_deleted', { persona_id: first.id });
  assert.ok(render(first.id).includes(i18n.t('personas:deletedPersona')));
  assert.match(render(second.id), /Second/);
  const failed = deferred();
  api.listPersonas = () => failed.promise;
  const reading = personas.getState().reload();
  assert.ok(render('unknown').includes(i18n.t('personas:assistant')));
  failed.reject(new Error('List unavailable'));
  await assert.rejects(reading, /List unavailable/);
  assert.equal(personas.getState().error, 'Error: List unavailable');
  assert.match(render(second.id), /Second/);
  assert.ok(render('unknown').includes(i18n.t('personas:assistant')));
  api.listPersonas = async () => [{ ...first, name: 'Final', avatar_attachment_id: null }, second];
  await personas.getState().reload();
}
console.log('live persona identities, deletions, pending list races and failed reads: ok');
