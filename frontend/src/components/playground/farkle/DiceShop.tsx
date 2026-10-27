import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { DICE_TYPES, type SpecialType } from './dice';
import { canTradeDice, type DiceTrade, type Inventory } from './economy';
import { DiceRow } from './DiceRow';

export function DiceShop({ inventory, previews, disabled, onTrade }: {
  inventory: Inventory; previews: { die: typeof DICE_TYPES[number]; url: string }[];
  disabled: boolean; onTrade: (type: SpecialType, action: DiceTrade) => void;
}) {
  const { t } = useTranslation('common');
  return <div className="farkle-dice-list min-h-0 overflow-y-auto">
    <ul className="farkle-dice-grid" data-shop>
      {previews.map(({ die, url }) => die.category === 'special' ? <DiceRow key={die.id} type={die.id} preview={url}
        quantity={t('farkle.owned', { count: inventory.special[die.id] })} quantityBelowName>
        <div className="flex shrink-0 items-center gap-1">
          {inventory.special[die.id] > 0 ? <Button variant="destructive" disabled={disabled || !canTradeDice(inventory, die.id, 'sell')}
            onClick={() => onTrade(die.id, 'sell')}>{t('farkle.sellDie')}</Button> : null}
          <Button variant="outline" disabled={disabled || !canTradeDice(inventory, die.id, 'buy')}
            onClick={() => onTrade(die.id, 'buy')}>{t('farkle.buyDie')}</Button>
        </div>
      </DiceRow> : null)}
    </ul>
  </div>;
}
