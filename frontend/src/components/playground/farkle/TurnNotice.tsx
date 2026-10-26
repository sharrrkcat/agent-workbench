import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { GameState } from './state';

export function TurnNotice({ state }: { state: GameState }) {
  const { t } = useTranslation('common');
  const [visible, setVisible] = useState(false);
  const active = state.playing && !state.winner;
  useEffect(() => {
    setVisible(active && state.player === 'B');
    if (!active || state.player !== 'B') return;
    const timer = setTimeout(() => setVisible(false), 1800);
    return () => clearTimeout(timer);
  }, [active, state.player, state.turnId]);

  if (!active || (state.player === 'B' && !visible)) return null;
  return <div key={state.turnId} className="farkle-turn" data-turn-notice={state.player} role="status">
    <div className="farkle-score-heading">{t(state.player === 'B' ? 'farkle.yourTurn' : 'farkle.opponentTurn')}</div>
  </div>;
}
