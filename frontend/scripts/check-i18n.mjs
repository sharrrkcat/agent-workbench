import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const root = path.resolve('src/i18n/resources');
const locales = ['en', 'zh-CN'];

function flatten(value, prefix = '') {
  return Object.entries(value).flatMap(([key, child]) => {
    const nextKey = prefix ? `${prefix}.${key}` : key;
    return child && typeof child === 'object' && !Array.isArray(child) ? flatten(child, nextKey) : [nextKey];
  });
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

let failed = false;
const namespaces = fs.readdirSync(path.join(root, 'en')).filter((file) => file.endsWith('.json')).sort();

for (const locale of locales) {
  for (const namespace of namespaces) {
    const file = path.join(root, locale, namespace);
    if (!fs.existsSync(file)) {
      console.error(`[i18n] Missing ${locale}/${namespace}`);
      failed = true;
      continue;
    }
    readJson(file);
  }
}

for (const namespace of namespaces) {
  const enKeys = new Set(flatten(readJson(path.join(root, 'en', namespace))));
  const zhKeys = new Set(flatten(readJson(path.join(root, 'zh-CN', namespace))));
  const missingZh = [...enKeys].filter((key) => !zhKeys.has(key));
  const missingEn = [...zhKeys].filter((key) => !enKeys.has(key));
  if (missingZh.length || missingEn.length) {
    failed = true;
    console.error(`[i18n] Key mismatch in ${namespace}`);
    for (const key of missingZh) console.error(`  missing zh-CN: ${key}`);
    for (const key of missingEn) console.error(`  missing en: ${key}`);
  }
}

if (failed) {
  process.exitCode = 1;
} else {
  console.log(`[i18n] ${namespaces.length} namespaces aligned for en and zh-CN.`);
}
