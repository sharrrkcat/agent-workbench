import assert from 'node:assert/strict';
import React from 'react';
import { createModuleLoader, mockModule } from './module-loader.mjs';

// Exercise the confirmation promise lifecycle; mounted focus behavior is covered in Playwright.
const slots = [];
let cursor = 0,
  cleanup;
const load = createModuleLoader({
  react: mockModule({
    ...React,
    useState(initial) {
      const index = cursor++;
      slots[index] ??= { value: initial };
      return [
        slots[index].value,
        (value) => {
          slots[index].value = value;
        },
      ];
    },
    useRef(initial) {
      return (slots[cursor++] ??= { current: initial });
    },
    useCallback(callback) {
      return callback;
    },
    useEffect(effect) {
      const value = effect();
      if (value) cleanup ??= value;
    },
  }),
  'react-i18next': mockModule({ useTranslation: () => ({ t: (key) => key }) }),
});
const { useConfirmDialog } = (await load('../src/hooks/useConfirmDialog.tsx')).exports;
const { AlertDialogAction, AlertDialogCancel } = (await load('../src/components/ui/alert-dialog.tsx'))
  .exports;
const render = (active = true) => {
  cursor = 0;
  return useConfirmDialog(active);
};
function descendants(node) {
  if (Array.isArray(node)) return node.flatMap(descendants);
  if (!React.isValidElement(node)) return [];
  return [node, ...descendants(node.props.children)];
}
let owner = render();
const first = owner.confirm('Delete the selected resource?', { destructive: true });
let settled = false;
first.then(() => {
  settled = true;
});
assert.equal(await owner.confirm('A second request'), false);
assert.equal(settled, false);
owner = render();
assert.equal(owner.confirmation.props.open, true);
const action = descendants(owner.confirmation).find((node) => node.type === AlertDialogAction);
assert.equal(action.props.variant, 'destructive');
action.props.onClick();
assert.equal(await first, true);
assert.equal(render().confirmation.props.open, false);

const cancelled = owner.confirm('Leave without saving?');
owner = render();
descendants(owner.confirmation)
  .find((node) => node.type === AlertDialogCancel)
  .props.onClick();
assert.equal(await cancelled, false);
const escaped = owner.confirm('Escape this request');
render().confirmation.props.onOpenChange(false);
assert.equal(await escaped, false);
const unmounted = owner.confirm('Owner removed before answering');
cleanup();
assert.equal(await unmounted, false);
owner = render();
const hidden = owner.confirm('Hidden settings view');
assert.equal(render(false).confirmation.props.open, false);
assert.equal(await hidden, false);
console.log('Confirmation accepts, cancels, rejects overlapping requests and resolves false on unmount.');
