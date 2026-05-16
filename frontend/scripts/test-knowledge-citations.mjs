import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/utils/knowledgeCitations.ts', import.meta.url), 'utf8');
const transformed = source
  .replace(/export type ParsedKnowledgeCitation = \{[\s\S]*?\};\n\n/, '')
  .replace(/\bexport /g, '')
  .replace(/: ParsedKnowledgeCitation \| null/g, '')
  .replace(/: string\[\]/g, '')
  .replace(/: string/g, '')
  .replace(/new Set<string>\(\)/g, 'new Set()')
  .concat('\nexports.parseKnowledgeCitationToken = parseKnowledgeCitationToken;');

const context = { exports: {}, Set, Number };
vm.runInNewContext(transformed, context, { filename: 'knowledgeCitations.ts' });

const { parseKnowledgeCitationToken } = context.exports;
const parsed = (token) => JSON.parse(JSON.stringify(parseKnowledgeCitationToken(token)));

assert.deepEqual(parsed('[K1]'), { token: '[K1]', labels: ['K1'] });
assert.deepEqual(parsed('[K12]'), { token: '[K12]', labels: ['K12'] });
assert.deepEqual(parsed('[K1, K2]'), { token: '[K1, K2]', labels: ['K1', 'K2'] });
assert.deepEqual(parsed('[K1,K2,K5]'), { token: '[K1,K2,K5]', labels: ['K1', 'K2', 'K5'] });
assert.deepEqual(parsed('[K1-K3]'), { token: '[K1-K3]', labels: ['K1', 'K2', 'K3'] });
assert.deepEqual(parsed('[K1–K3]'), { token: '[K1–K3]', labels: ['K1', 'K2', 'K3'] });
assert.deepEqual(parsed('[K1, K3-K5]'), { token: '[K1, K3-K5]', labels: ['K1', 'K3', 'K4', 'K5'] });
assert.deepEqual(parsed('[K1,K1,K2]'), { token: '[K1,K1,K2]', labels: ['K1', 'K2'] });

assert.equal(parseKnowledgeCitationToken('[1]'), null);
assert.equal(parseKnowledgeCitationToken('[k1]'), null);
assert.equal(parseKnowledgeCitationToken('【K1】'), null);
assert.equal(parseKnowledgeCitationToken('[K5-K1]'), null);
assert.equal(parseKnowledgeCitationToken('[K1-K25]'), null);

console.log('[OK] Knowledge citation parser tests passed');
