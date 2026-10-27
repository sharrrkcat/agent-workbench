import { useCallback, useEffect, useRef, useState } from 'react';
import { awardDice, readInventory, saveInventory, type Inventory, type Reward, type LevelId } from './economy';
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
  const persist = useCallback((inventory: Inventory) => {
    try {
      saveInventory(window.localStorage, inventory);
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
    if (collection.error === 'save' && settlement.current) persist(settlement.current.inventory);
    else setCollection(loadCollection());
  }
  return { ...collection, reward, retry };
}
