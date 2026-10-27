import { useId, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';
import { cn } from '@/lib/utils';
import { DICE_TYPES, type DieType } from './dice';

export function DiceRow({ type, preview, quantity, quantityBelowName = false, selectedCount, unowned = false, children }: {
  type: DieType; preview: string; quantity?: string; quantityBelowName?: boolean; selectedCount?: number; unowned?: boolean; children?: ReactNode;
}) {
  const { t, i18n } = useTranslation('common');
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const descriptionId = useId();
  const { weights } = DICE_TYPES.find((die) => die.id === type)!;
  const sum = weights.reduce((total: number, weight) => total + weight, 0);
  const faces = weights.map((weight, index) => ({
    label: type === 'devil' && index === 0 ? t('farkle.wildFace') : t('farkle.faceValue', { value: index + 1 }),
    percent: (weight / sum).toLocaleString(i18n.language, { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 }),
  }));
  // Handle quantity taps so Chromium cannot retarget them to the adjacent name button.
  const count = quantity === undefined ? null : <span className={cn('shrink-0 tabular-nums',
    quantityBelowName && 'px-2 text-[11px] leading-4 text-muted-foreground')} data-inventory-count
    onClick={() => setOpen(false)}>{quantity}</span>;

  return <HoverCard open={open} onOpenChange={(next, details) => {
    // Focus/touch activation outlives the synthetic mouseleave from a tap.
    if (!next && details.reason === 'trigger-hover' && document.activeElement === trigger.current) {
      details.cancel();
      return;
    }
    setOpen(next);
  }}>
    <li className="flex min-w-0 items-center gap-2" data-inventory-type={type} data-loadout-count={selectedCount}
      style={{ '--farkle-selected-count': selectedCount } as CSSProperties}>
      <img className={cn('size-10 shrink-0 rounded-md',
        unowned && 'grayscale transition-[filter] duration-150 hover:grayscale-0 motion-reduce:transition-none')} src={preview} alt="" />
      <div className="flex min-w-0 flex-1 flex-col items-start">
        <HoverCardTrigger delay={150} closeDelay={150} render={<Button ref={trigger} variant="ghost"
          className={cn('h-auto max-w-full min-w-0 justify-start whitespace-normal text-left',
            quantityBelowName && quantity !== undefined && 'pointer-coarse:min-h-0')} aria-describedby={descriptionId}
          onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onClick={() => setOpen(true)} />}>
          {t(`farkle.dice.${type}`)}
        </HoverCardTrigger>
        {quantityBelowName ? count : null}
      </div>
      <span className="sr-only" id={descriptionId}>{faces.map(({ label, percent }) => `${label}: ${percent}`).join(', ')}</span>
      {!quantityBelowName ? count : null}
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
