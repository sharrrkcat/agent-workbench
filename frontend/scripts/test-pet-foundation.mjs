import assert from 'node:assert/strict';
import React from 'react';
import { createModuleLoader, mockModule } from './module-loader.mjs';

const load = createModuleLoader();
const { currentRun, petTaskState } = (await load('../src/components/pet/petState.ts')).exports;
const at = (fraction) => `2026-09-07T00:00:00.${fraction}Z`;
const run = { run_id: 'run', session_id: 'session', status: 'RUNNING', updated_at: at('000001'),
  progress_message: 'Executing', progress_current: 0, progress_total: 8 };
const step = { step_id: 'step', run_id: 'run', status: 'running', kind: 'model', order: 1 };
const done = { ...run, run_id: 'done', status: 'DONE', updated_at: at('000009') };
assert.equal(currentRun([done, run], 'session'), run);
assert.equal(currentRun([run], 'other'), null);
assert.equal(currentRun([run]), null);
assert.equal(currentRun([{ ...done, updated_at: at('000008') }, done], 'session'), done);
assert.equal(petTaskState([], {}, 'session').status, 'IDLE');
for (const status of ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER', 'DONE', 'FAILED', 'CANCELLED', 'INTERRUPTED']) {
  const state = petTaskState([{ ...run, status }], { run: [step] }, 'session');
  assert.equal(state.status, status);
  assert.equal(state.progress_current, 0);
  assert.equal(state.progress_total, 8);
  assert.equal(state.step_kind, ['DONE', 'FAILED', 'CANCELLED', 'INTERRUPTED'].includes(status) ? null : 'model');
}
const approval = { ...step, step_id: 'approval', kind: 'approval', order: 0 };
assert.equal(petTaskState([{ ...run, status: 'WAITING_FOR_USER' }], { run: [step, approval] }, 'session').step_kind, 'approval');
assert.equal(petTaskState([{ ...run, steps: [approval] }], { run: [] }, 'session').step_kind, null);
assert.equal(petTaskState([run], { run: [{ ...step, run_id: 'other' }] }, 'session').step_kind, null);

// Exercise the real hook's event handlers and effects without mounting a Pet UI.
function hookHarness() {
  const slots = [];
  let cursor = 0, dirty = false, pending = [];
  const hooks = {
    useState(initial) {
      const index = cursor++;
      if (!slots[index]) slots[index] = { value: typeof initial === 'function' ? initial() : initial };
      return [slots[index].value, (next) => {
        const value = typeof next === 'function' ? next(slots[index].value) : next;
        if (!Object.is(value, slots[index].value)) { slots[index].value = value; dirty = true; }
      }];
    },
    useRef(initial) {
      const index = cursor++;
      return slots[index] ??= { current: initial };
    },
    useEffect(effect, deps) {
      const index = cursor++;
      const previous = slots[index];
      if (!previous || deps.some((dep, i) => !Object.is(dep, previous.deps[i]))) {
        pending.push(() => { previous?.cleanup?.(); slots[index] = { deps, cleanup: effect() }; });
      }
    },
  };
  return {
    hooks,
    render(component) {
      let result;
      for (let round = 0; round < 20; round++) {
        dirty = false; cursor = 0; pending = [];
        result = component();
        for (const effect of pending) effect();
        if (!dirty) return result;
      }
      throw new Error('Hook did not settle');
    },
    unmount() { for (const slot of slots) slot?.cleanup?.(); },
  };
}
const harness = hookHarness();
const hookLoad = createModuleLoader({ react: mockModule({ ...React, ...harness.hooks }) });
const { usePetPosition, clampPosition } = (await hookLoad('../src/components/pet/usePetPosition.ts')).exports;
const listeners = new Map();
globalThis.window = { innerWidth: 390, innerHeight: 844,
  addEventListener(name, handler) { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(handler); },
  removeEventListener(name, handler) { listeners.get(name)?.delete(handler); },
};
globalThis.fetch = () => { throw new Error('Dragging must use its callback, not a package/settings API'); };
const emit = (name, event) => { for (const handler of [...(listeners.get(name) || [])]) handler(event); };
const commits = [];
const options = { saved: { mode: 'custom', x: 50, y: 60 }, width: 100, height: 80,
  onCommit: async (position) => { commits.push(position); } };
const render = () => harness.render(() => usePetPosition(options));
const pointer = (values = {}) => ({ button: 0, isPrimary: true, pointerId: 1, clientX: 10, clientY: 10, preventDefault() {}, ...values });
const settle = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };
let result = render();
assert.deepEqual(result.position, { x: 50, y: 60 });
assert.equal(result.startDrag(pointer({ button: 1 })), false);
assert.equal(result.startDrag(pointer({ isPrimary: false })), false);
assert.equal(result.startDrag(pointer()), true);
result = render();
assert.equal(result.dragging, true);
emit('pointermove', pointer({ pointerId: 2, clientX: 300 }));
assert.deepEqual(render().position, { x: 50, y: 60 });
emit('pointermove', pointer({ clientX: 1000, clientY: -500 }));
assert.deepEqual(render().position, { x: 282, y: 8 });
emit('pointerup', pointer({ clientX: 1000, clientY: -500 }));
result = render();
assert.equal(result.dragging, false);
assert.equal(result.saving, true);
await settle();
assert.deepEqual(commits, [{ mode: 'custom', x: 282, y: 8 }]);
assert.equal(render().saving, false);
result = render();
result.startDrag(pointer());
render();
emit('pointermove', pointer({ clientX: -1000, clientY: 100 }));
render();
emit('pointercancel', pointer());
assert.deepEqual(render().position, { x: 282, y: 8 });
assert.equal(commits.length, 1);
window.innerWidth = 150; window.innerHeight = 100;
emit('resize', {});
assert.deepEqual(render().position, { x: 42, y: 8 });
options.saved = { mode: 'default', x: null, y: null };
assert.deepEqual(render().position, { x: 22, y: 8 });
options.width = 200; options.height = 200;
assert.deepEqual(render().position, { x: 0, y: 0 });
assert.deepEqual(clampPosition({ x: NaN, y: Infinity }, 10, 10, { width: 15, height: 15 }), { x: 2.5, y: 2.5 });
options.onCommit = async () => { throw new Error('Position save failed'); };
result = render(); result.startDrag(pointer()); render(); emit('pointerup', pointer()); render();
await settle();
assert.equal(render().error, 'Position save failed');
harness.unmount();
assert.ok([...listeners.values()].every((handlers) => handlers.size === 0));
console.log('Pet position callback, dragging/cancellation, viewport bounds and task-state foundations passed.');
