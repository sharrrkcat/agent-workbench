import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

for (const script of [
  'check-i18n',
  'check-doc-links',
  'test-module-loader',
  'test-i18n',
  'test-contracts',
  'test-resource-management',
  'test-session-settings',
  'test-session-actions',
  'test-confirm-dialog',
  'test-pet-foundation',
  'test-model-stream',
  'test-runtime-maintenance',
  'test-tts',
  'test-wd14',
  'test-siglip',
  'test-text-embeddings',
  'test-rerankers',
  'test-asr',
  'test-transformers',
  'test-harness',
  'test-chat-presentation',
  'test-url-helpers',
]) {
  const result = spawnSync(process.execPath, [fileURLToPath(new URL(`./${script}.mjs`, import.meta.url))], {
    stdio: 'inherit',
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status || 1);
}
