import assert from 'node:assert/strict';
import { createInstance } from 'i18next';
import { createModuleLoader, mockModule } from './module-loader.mjs';

for (const stored of [undefined, 'en', 'zh-CN', 'invalid']) {
  const values = new Map([['agent-workbench.locale', 'zh-CN']]);
  if (stored !== undefined) values.set('cogita.locale', stored);
  globalThis.window = {
    localStorage: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
    },
  };
  const load = createModuleLoader({ i18next: mockModule({ default: createInstance() }) });
  const { default: i18n, changeLocale } = (await load('../src/i18n/index.ts')).exports;
  assert.equal(i18n.language, stored === 'zh-CN' ? 'zh-CN' : 'en');
  for (const locale of ['en', 'zh-CN']) {
    await changeLocale(locale);
    assert.equal(i18n.t('appName'), 'Cogita');
    assert.equal(values.get('cogita.locale'), locale);
    assert.equal(values.get('agent-workbench.locale'), 'zh-CN');
  }
}
delete globalThis.window;
console.log('Cogita locale selection, persistence and bilingual branding passed.');
