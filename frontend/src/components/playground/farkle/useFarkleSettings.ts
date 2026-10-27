import { useState } from 'react';
import { DEFAULT_OPPONENT_MODE, readFarkleSettings, saveFarkleSettings } from './settings';
import type { OpponentDiceMode } from './opponentDice';

type SettingsState = { mode: OpponentDiceMode; error: 'load' | 'save' | null; pending: OpponentDiceMode | null };
function loadSettings(): SettingsState {
  try { return { mode: readFarkleSettings(window.localStorage), error: null, pending: null }; }
  catch { return { mode: DEFAULT_OPPONENT_MODE, error: 'load', pending: null }; }
}

export function useFarkleSettings() {
  const [settings, setSettings] = useState(loadSettings);
  function setMode(mode: OpponentDiceMode) {
    try { saveFarkleSettings(window.localStorage, mode); }
    catch { setSettings((current) => ({ ...current, error: 'save', pending: mode })); return; }
    setSettings({ mode, error: null, pending: null });
  }
  function retry() {
    if (settings.pending) setMode(settings.pending);
    else setSettings(loadSettings());
  }
  function reset() { setSettings({ mode: DEFAULT_OPPONENT_MODE, error: null, pending: null }); }
  return { mode: settings.mode, error: settings.error, setMode, retry, reset };
}
