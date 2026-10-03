import assert from 'node:assert/strict';
import { createModuleLoader } from './module-loader.mjs';

const { latestContextUsage, configuredContextWindow } = (await createModuleLoader()('../src/components/contextUsage.ts')).exports;
const profile = { id: 'p', kind: 'llm', source: { type: 'provider' }, context_window_tokens: 32768 };
const budget = { configured_window_tokens: 32768, window_tokens: 32768, input_tokens: 9000,
  input_budget_tokens: 25395, output_tokens: 4096, margin_tokens: 3277, removed_turns: 2, counting: 'estimated' };
const step = (order, input = 8126, status = 'completed', output = 10) => ({ order, kind: 'model', status,
  metadata: { context: { budget }, llm: { model_profile_id: 'p', model: 'model',
    usage: input === null ? null : { prompt_tokens: input, completion_tokens: output, total_tokens: input + (output ?? 0),
      prompt_tokens_details: { cached_tokens: 1000 }, completion_tokens_details: { reasoning_tokens: 3 } } } } });
const run = (steps, session_id = 's') => ({ kind: 'chat', session_id, created_at: '2026-10-03', steps });
assert.equal(latestContextUsage([], 's', profile), null);
assert.equal(latestContextUsage([run([step(1)])], 'other', profile), null);
assert.equal(latestContextUsage([run([step(1)])], undefined, profile), null);
let result = latestContextUsage([run([step(1), step(2, 10000, 'running')])], 's', profile);
assert.equal(result.used, 8136);
assert.equal(result.ratio, 8136 / 32768);
assert.equal(result.budget.removed_turns, 2);
result = latestContextUsage([run([step(1), step(2, null)])], 's', profile);
assert.equal(result.used, null);
assert.equal(result.ratio, null);
assert.equal(latestContextUsage([run([step(1), { kind: 'model', status: 'failed', order: 2 }])], 's', profile), null);
assert.equal(latestContextUsage([run([step(1)])], 's', { ...profile, id: 'other' }), null);
assert.equal(latestContextUsage([run([step(1)])], 's', { ...profile, context_window_tokens: 8192 }), null);
assert.equal(latestContextUsage([run([step(2, 200), step(1, 100)])], 's', profile).used, 210);
assert.equal(configuredContextWindow({ ...profile, source: { type: 'local', execution_options: {} } }), 4096);
assert.equal(configuredContextWindow({ ...profile, context_window_tokens: null }), null);
// A later call replaces the earlier one; neither reserve nor detail counts are added.
assert.equal(latestContextUsage([run([step(1), step(2, 200)])], 's', profile).used, 210);
assert.equal(latestContextUsage([run([step(1, 200, 'completed', 0)])], 's', profile).used, 200);
assert.equal(latestContextUsage([run([step(1, 0, 'completed', 0)])], 's', profile).ratio, 0);
for (const missing of [null, undefined]) {
  for (const field of ['prompt_tokens', 'completion_tokens']) {
    const incomplete = step(2);
    incomplete.metadata.llm.usage[field] = missing;
    const unknown = latestContextUsage([run([step(1), incomplete])], 's', profile);
    assert.equal(unknown.used, null);
    assert.equal(unknown.ratio, null);
  }
}
result = latestContextUsage([run([step(1, 32768, 'completed', 10)])], 's', profile);
assert.equal(result.used, 32778);
assert.ok(result.ratio > 1);
const limited = step(1, 300, 'completed', 10);
limited.metadata.context = { budget: { ...budget, window_tokens: 512 } };
assert.equal(latestContextUsage([run([limited])], 's', profile).ratio, 310 / 512);
const oldRun = { ...run([step(9, 100)]), created_at: '2026-10-02' };
const newRun = run([step(1, 200)]);
assert.equal(latestContextUsage([newRun, oldRun], 's', profile).used, 210);
assert.equal(latestContextUsage([oldRun], 's', profile).used, 110);
console.log('Context usage: per-call counts, unknown usage, running state, session/model/window isolation and deletion passed.');
