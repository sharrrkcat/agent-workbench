import { useCallback, useEffect, useRef, useState } from 'react';
import { appendHistory, matchRecord, readHistory, saveHistory, type MatchRecord } from './history';
import type { GameState } from './state';

type Collection = { records: MatchRecord[] | null; error: 'load' | 'save' | null };
function loadHistory(): Collection {
  try { return { records: readHistory(window.localStorage), error: null }; }
  catch { return { records: null, error: 'load' }; }
}

export function useMatchHistory(state: GameState) {
  const [collection, setCollection] = useState(loadHistory);
  const settlement = useRef<{ record: MatchRecord; queued: boolean } | null>(null);
  const pending = useRef<MatchRecord[] | null>(null);
  const persist = useCallback((records: MatchRecord[]) => {
    pending.current = records;
    try {
      saveHistory(window.localStorage, records);
      pending.current = null;
      setCollection({ records, error: null });
    } catch { setCollection({ records, error: 'save' }); }
  }, []);

  useEffect(() => {
    if (!state.winner) { settlement.current = null; return; }
    // Freeze time and data before a save or reward retry can run.
    settlement.current ??= { record: matchRecord(state, Date.now()), queued: false };
    if (!collection.records || settlement.current.queued) return;
    settlement.current.queued = true;
    persist(appendHistory(collection.records, settlement.current.record));
  }, [state, collection.records, persist]);

  function retry() {
    if (pending.current) persist(pending.current);
    else setCollection(loadHistory());
  }
  function reset() {
    pending.current = null;
    settlement.current = null;
    setCollection({ records: [], error: null });
  }
  return { ...collection, retry, reset };
}
