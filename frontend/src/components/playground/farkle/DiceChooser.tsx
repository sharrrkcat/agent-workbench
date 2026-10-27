import { useTranslation } from 'react-i18next';
import { Minus, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { DICE_TYPES, type DiceCounts } from './dice';
import { adjustLoadout, canAdjustLoadout } from './loadout';
import { DiceRow } from './DiceRow';

export function DiceChooser({ counts, available, previews, showInventory, onChange }: {
  counts: DiceCounts; available: DiceCounts; previews: { die: typeof DICE_TYPES[number]; url: string }[];
  showInventory: boolean; onChange: (counts: DiceCounts) => void;
}) {
  const { t } = useTranslation('common');
  const order = previews.map(({ die }) => die.id);
  return <div className="farkle-dice-list min-h-0 overflow-y-auto">
    <ul className="farkle-dice-grid" data-loadout>
      {previews.filter(({ die }) => available[die.id] > 0).map(({ die, url }) => <DiceRow key={die.id}
        type={die.id} preview={url} quantity={showInventory ? t('farkle.owned', { count: available[die.id] }) : undefined} quantityBelowName
        selectedCount={counts[die.id]}>
        <div className="flex shrink-0 items-center gap-1">
          <Button variant="outline" size="icon" aria-label={t('farkle.removeDie', { name: t(`farkle.dice.${die.id}`) })}
            disabled={!canAdjustLoadout(counts, available, die.id, -1)}
            onClick={() => onChange(adjustLoadout(counts, die.id, -1, order))}><Minus /></Button>
          <span className="w-4 text-center tabular-nums" data-selected-count>{counts[die.id]}</span>
          <Button variant="outline" size="icon" aria-label={t('farkle.addDie', { name: t(`farkle.dice.${die.id}`) })}
            disabled={!canAdjustLoadout(counts, available, die.id, 1)}
            onClick={() => onChange(adjustLoadout(counts, die.id, 1, order))}><Plus /></Button>
        </div>
      </DiceRow>)}
    </ul>
  </div>;
}
