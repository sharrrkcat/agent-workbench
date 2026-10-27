import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Empty, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card';
import { Pagination, PaginationContent, PaginationItem, PaginationLink, PaginationNext, PaginationPrevious } from '@/components/ui/pagination';
import { farkleHistoryUrl, type FarkleNavigate } from './navigation';
import type { DieType } from './dice';
import { dicePreview } from './materials';
import { formatDuration, historyPage, HISTORY_PAGE_SIZE, type MatchRecord } from './history';

function HistoryDie({ type, face, src, interactive }: { type: DieType; face: number; src: string; interactive: boolean }) {
  const { t } = useTranslation('common');
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const name = t(`farkle.dice.${type}`);
  return <HoverCard open={interactive && open} onOpenChange={(next, details) => {
    if (!next && details.reason === 'trigger-hover' && document.activeElement === trigger.current) {
      details.cancel(); return;
    }
    setOpen(next);
  }}>
    <HoverCardTrigger delay={150} closeDelay={150} render={<Button ref={trigger} variant="ghost" size="icon"
      className="h-8 w-[var(--farkle-history-die-size)] min-w-0 shrink-0 border-0 p-0 pointer-coarse:min-w-0"
      aria-label={name} data-history-die={type} data-preview-face={face}
      onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onClick={() => setOpen(true)} />}>
      <img className="size-[var(--farkle-history-die-size)] rounded-md" src={src} alt="" />
    </HoverCardTrigger>
    <HoverCardContent className="w-auto whitespace-nowrap" side="top">{name}</HoverCardContent>
  </HoverCard>;
}

export function FarkleHistory({ records, search, onNavigate, interactive }: {
  records: MatchRecord[] | null; search: string; onNavigate: FarkleNavigate; interactive: boolean;
}) {
  const { t, i18n } = useTranslation('common');
  const scroll = useRef<HTMLDivElement>(null);
  const previews = useRef(new Map<string, string>());
  const page = historyPage(search, records?.length ?? 0);
  const pages = Math.max(1, Math.ceil((records?.length ?? 0) / HISTORY_PAGE_SIZE));
  const visible = records?.slice((page - 1) * HISTORY_PAGE_SIZE, page * HISTORY_PAGE_SIZE) ?? [];
  const dates = useMemo(() => new Intl.DateTimeFormat(i18n.language, {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }), [i18n.language]);
  useEffect(() => { scroll.current?.scrollTo(0, 0); }, [page]);

  function diceGroup(dice: DieType[], side: 'player' | 'opponent') {
    const english = i18n.getFixedT('en', 'common');
    const ordered = [...dice].sort((a, b) => english(`farkle.dice.${a}`).localeCompare(english(`farkle.dice.${b}`), 'en'));
    return <div className={`farkle-history-dice farkle-history-${side}`} role="group" aria-label={t(`farkle.${side}`)}>
      <span className="farkle-history-side text-muted-foreground">{t(`farkle.${side}`)}</span>
      <div className="flex items-center gap-0.5">{ordered.map((type, index) => {
        const key = `${type}-${index + 1}`;
        if (!previews.current.has(key)) previews.current.set(key, dicePreview(type, index + 1).toDataURL());
        return <HistoryDie key={index} type={type} face={index + 1} src={previews.current.get(key)!} interactive={interactive} />;
      })}</div>
    </div>;
  }

  return <section className="farkle-history flex min-h-0 min-w-0 flex-1 flex-col" aria-label={t('farkle.history')}>
    <div ref={scroll} className="min-h-0 flex-1 overflow-y-auto p-4 max-[359px]:px-2" data-history-scroll>
      {records?.length === 0 ? <Empty className="h-full"><EmptyHeader><EmptyTitle>{t('farkle.historyEmpty')}</EmptyTitle></EmptyHeader></Empty> : null}
      <ol className="mx-auto flex max-w-[1200px] flex-col gap-2" aria-label={t('farkle.history')}>
        {visible.map((record, index) => <li key={`${record.startedAt}-${index}`} className="farkle-history-row rounded-lg border bg-card p-3 max-[359px]:px-2"
          data-history-record data-started-at={record.startedAt}>
          <div className="farkle-history-meta">
            <div className="farkle-history-time tabular-nums">
              <time className="farkle-history-start" dateTime={new Date(record.startedAt).toISOString()}>{dates.format(record.startedAt)}</time>
              <time className="farkle-history-duration text-muted-foreground" dateTime={`PT${record.durationSeconds}S`}
                aria-label={t('farkle.historyDuration', { duration: formatDuration(record.durationSeconds) })}>{formatDuration(record.durationSeconds)}</time>
            </div>
            <span className="farkle-history-outcome" data-outcome={record.winner === 'B' ? 'win' : 'loss'}>
              {t(record.winner === 'B' ? 'farkle.historyVictory' : 'farkle.historyDefeat')}
            </span>
          </div>
          <div className="farkle-history-body">
            {diceGroup(record.playerDice, 'player')}
            <div className="farkle-history-scores text-center tabular-nums">
              <span aria-label={`${t('farkle.player')}: ${record.playerScore}`} data-history-score="player">{record.playerScore}</span>
              <span className="text-muted-foreground" aria-label={`${t(record.level === null ? 'farkle.historyCustom' : 'farkle.goal')}: ${record.targetScore}`}>
                <span className="block text-[10px]" data-history-goal-label>{t(record.level === null ? 'farkle.historyCustom' : 'farkle.goal')}</span>
                <span data-history-score="goal">{record.targetScore}</span>
              </span>
              <span aria-label={`${t('farkle.opponent')}: ${record.opponentScore}`} data-history-score="opponent">{record.opponentScore}</span>
            </div>
            {diceGroup(record.opponentDice, 'opponent')}
          </div>
        </li>)}
      </ol>
    </div>
    {records && records.length > 0 ? <Pagination className="shrink-0 border-t p-3 max-[359px]:px-0">
      <PaginationContent>
        <PaginationItem><PaginationPrevious href={farkleHistoryUrl(page - 1)} aria-disabled={page === 1} tabIndex={page === 1 ? -1 : undefined}
          onClick={(event) => { event.preventDefault(); if (page > 1) void onNavigate(farkleHistoryUrl(page - 1)); }} /></PaginationItem>
        {Array.from({ length: pages }, (_, index) => index + 1).map((number) => <PaginationItem key={number}>
          <PaginationLink href={farkleHistoryUrl(number)} isActive={page === number}
            onClick={(event) => { event.preventDefault(); void onNavigate(farkleHistoryUrl(number)); }}>{number}</PaginationLink>
        </PaginationItem>)}
        <PaginationItem><PaginationNext href={farkleHistoryUrl(page + 1)} aria-disabled={page === pages} tabIndex={page === pages ? -1 : undefined}
          onClick={(event) => { event.preventDefault(); if (page < pages) void onNavigate(farkleHistoryUrl(page + 1)); }} /></PaginationItem>
      </PaginationContent>
    </Pagination> : null}
  </section>;
}
