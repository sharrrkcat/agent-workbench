import { useCallback, useEffect, useRef, useState } from 'react';
import { awardDice, canModifyInventory, modifyInventory, newInventory, readInventory, saveInventory,
  type Inventory, type InventoryAction, type Reward, type LevelId } from './economy';
import type { PlayerId } from './state';

type Collection = { inventory: Inventory | null; error: 'load' | 'save' | null };
function loadCollection(): Collection {
  try { return { inventory: readInventory(window.localStorage), error: null }; }
  catch { return { inventory: null, error: 'load' }; }
}

export function useInventory(winner: PlayerId | null, level: LevelId | null) {
  const [collection, setCollection] = useState(loadCollection);
  const [reward, setReward] = useState<Reward | null>(null);
  const settlement = useRef<ReturnType<typeof awardDice> | null>(null);
  const pending = useRef<Inventory | null>(null);
  const persist = useCallback((inventory: Inventory) => {
    pending.current = inventory;
    try {
      saveInventory(window.localStorage, inventory);
      pending.current = null;
      setCollection({ inventory, error: null });
    } catch { setCollection({ inventory, error: 'save' }); }
  }, []);

  useEffect(() => {
    if (!winner || level === null) { settlement.current = null; setReward(null); return; }
    if (!collection.inventory || settlement.current) return;
    // Fix the reward before storage or rendering can fail/repeat.
    const result = awardDice(collection.inventory, level, winner === 'B');
    settlement.current = result;
    setReward(result.reward);
    persist(result.inventory);
  }, [winner, level, collection.inventory, persist]);

  function retry() {
    if (pending.current) persist(pending.current);
    else setCollection(loadCollection());
  }
  function modify(action: InventoryAction) {
    if (!collection.inventory || collection.error || !canModifyInventory(collection.inventory, action)) return;
    persist(modifyInventory(collection.inventory, action));
  }
  function reset() {
    pending.current = null;
    settlement.current = null;
    setReward(null);
    setCollection({ inventory: newInventory(), error: null });
  }
  return { ...collection, reward, retry, modify, reset };
}
