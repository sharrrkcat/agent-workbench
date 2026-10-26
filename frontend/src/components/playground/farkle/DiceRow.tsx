import { useId, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';
import { DICE_TYPES, type DieType } from './dice';

export function DiceRow({ type, preview, quantity, inlineQuantity = false, children }: {
  type: DieType; preview: string; quantity: string; inlineQuantity?: boolean; children?: ReactNode;
}) {
  const { t, i18n } = useTranslation('common');
  const [open, setOpen] = useState(false);
  const descriptionId = useId();
  const { weights } = DICE_TYPES.find((die) => die.id === type)!;
  const sum = weights.reduce((total: number, weight) => total + weight, 0);
  const faces = weights.map((weight, index) => ({
    label: type === 'devil' && index === 0 ? t('farkle.wildFace') : t('farkle.faceValue', { value: index + 1 }),
    percent: (weight / sum).toLocaleString(i18n.language, { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 }),
  }));
  const count = <span className="shrink-0" data-inventory-count>{quantity}</span>;

  return <HoverCard open={open} onOpenChange={setOpen}>
    <li className="flex items-center gap-2" data-inventory-type={type}>
      <img className="size-10 shrink-0 rounded-md" src={preview} alt="" />
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-1">
        <HoverCardTrigger delay={150} closeDelay={150} render={<Button variant="ghost"
          className="h-auto max-w-full min-w-0 justify-start whitespace-normal text-left" aria-describedby={descriptionId}
          onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onClick={() => setOpen(true)} />}>
          {t(`farkle.dice.${type}`)}
        </HoverCardTrigger>
        {inlineQuantity ? count : null}
      </div>
      <span className="sr-only" id={descriptionId}>{faces.map(({ label, percent }) => `${label}: ${percent}`).join(', ')}</span>
      {!inlineQuantity ? count : null}
      {children}
    </li>
    <HoverCardContent align="start" data-dice-probabilities={type}>
      <div className="grid grid-cols-6 gap-2 text-center tabular-nums">
        {faces.map(({ label, percent }, index) => <span key={index} aria-label={`${label}: ${percent}`}
          data-probability-face={index + 1}>{percent}</span>)}
      </div>
    </HoverCardContent>
  </HoverCard>;
}
