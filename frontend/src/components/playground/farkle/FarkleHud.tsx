import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Kbd } from '@/components/ui/kbd';
import { selection, type GameState } from './state';

export function FarkleHud({ state, disabled, onHold, onStore, onPass }: {
  state: GameState; disabled: boolean; onHold: () => void; onStore: () => void; onPass: () => void;
}) {
  const { t } = useTranslation('common');
  const selected = selection(state);
  const largestScore = Math.max(state.target, ...Object.values(state.totals), ...Object.values(state.rounds));
  return <div className="farkle-hud">
    <div className="farkle-score" role="group" aria-label={t('farkle.scores')}
      data-score-digits={Math.min(6, String(largestScore).length)} data-large-values={largestScore >= 1_000_000}>
      <div className="farkle-score-player">
        <div className="farkle-score-heading">{t('farkle.player')}</div>
        <div className="farkle-score-total" data-wrap={state.totals.B >= 1_000_000}>{state.totals.B}</div>
        <div data-score="B-round" data-wrap={state.rounds.B >= 1_000_000}>{state.rounds.B}</div><div data-score="B-selected">{selection(state, 'B').score}</div>
      </div>
      <div className="farkle-score-goal">
        <div className="farkle-score-heading">{t('farkle.goal')}</div>
        <div className="farkle-score-total" data-target-score={state.target} data-wrap={state.target >= 1_000_000}>{state.target}</div>
        <div>{t('farkle.round')}</div><div>{t('farkle.selected')}</div>
      </div>
      <div className="farkle-score-opponent">
        <div className="farkle-score-heading">{t('farkle.opponent')}</div>
        <div className="farkle-score-total" data-wrap={state.totals.A >= 1_000_000}>{state.totals.A}</div>
        <div data-score="A-round" data-wrap={state.rounds.A >= 1_000_000}>{state.rounds.A}</div><div data-score="A-selected">{selection(state, 'A').score}</div>
      </div>
    </div>
    <div className="farkle-actions">
      <div className="farkle-action-row farkle-action-hold">
        <Button variant="secondary" className="h-auto min-h-8 min-w-0 shrink py-1.5" disabled={disabled || !state.hoverId} onClick={onHold}
          aria-label={t('farkle.hold')} aria-keyshortcuts="E">
          <span>{t('farkle.hold')}</span>
        </Button>
        <Kbd className="pointer-coarse:hidden" aria-hidden="true">E</Kbd>
      </div>
      <div className="farkle-action-row">
        <Button variant="secondary" className="h-auto min-h-8 min-w-0 shrink py-1.5" disabled={disabled || !selected.valid} onClick={onStore}
          aria-label={t('farkle.scoreContinue')} aria-keyshortcuts="F">
          <span>{t('farkle.scoreContinue')}</span>
        </Button>
        <Kbd className="pointer-coarse:hidden" aria-hidden="true">F</Kbd>
      </div>
      <div className="farkle-action-row">
        <Button variant="secondary" className="h-auto min-h-8 min-w-0 shrink py-1.5"
          disabled={disabled || (selected.dice.length > 0 && !selected.valid)} onClick={onPass}
          aria-label={t('farkle.pass')} aria-keyshortcuts="Q">
          <span>{t('farkle.pass')}</span>
        </Button>
        <Kbd className="pointer-coarse:hidden" aria-hidden="true">Q</Kbd>
      </div>
    </div>
  </div>;
}
