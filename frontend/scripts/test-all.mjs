import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

for (const script of [
  'check-i18n',
  'check-doc-links',
  'test-contracts',
  'test-session-settings',
  'test-pet-foundation',
  'test-model-stream',
  'test-harness',
  'test-chat-presentation',
  'test-knowledge-citations',
  'test-url-helpers',
]) {
  const result = spawnSync(process.execPath, [fileURLToPath(new URL(`./${script}.mjs`, import.meta.url))], {
    stdio: 'inherit',
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status || 1);
}
