import { Fragment, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, Coins, LogOut, Minus, Package, Plus, ShoppingBag } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Alert, AlertAction, AlertDescription } from '@/components/ui/alert';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Field, FieldLabel } from '@/components/ui/field';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';
import { Sidebar, SidebarContent, SidebarFooter, SidebarHeader, SidebarInset, SidebarMenu,
  SidebarMenuButton, SidebarMenuItem, SidebarTrigger, useSidebar } from '@/components/ui/sidebar';
import type { SettingsNavigate } from '@/components/settings/navigation';
import { playgroundUrl } from '../navigation';
import { FarkleTable } from './FarkleTable';
import { dicePreview } from './materials';
import { DICE_TYPES, drawOpponentDice, NORMAL_COUNT, rollValues, SPECIAL_LIMIT, type DiceCounts } from './dice';
import { inventoryPool, LEVELS, type TargetScore } from './economy';
import { gameReducer, initialGame } from './state';
import { useInventory } from './useInventory';
import { rewardGroups } from './rewards';
import { loadoutDice, loadoutSize, readLoadout, saveLoadout } from './loadout';
import { DiceRow } from './DiceRow';
import { useOpponent } from './useOpponent';

type Modal = 'newGame' | 'chooseDice' | 'myDice' | 'shop' | 'result';

export default function FarklePage({ onNavigate }: { onNavigate: SettingsNavigate }) {
  const { t, i18n } = useTranslation('common');
  const { setOpenMobile, isMobile, openMobile } = useSidebar();
  const [state, dispatch] = useReducer(gameReducer, initialGame);
  const { inventory, reward, error: storageError, retry } = useInventory(state.winner, state.target);
  const [modal, setModal] = useState<Modal | null>(null);
  const [ready, setReady] = useState(false);
  const [target, setTarget] = useState<TargetScore>(1500);
  const [draft, setDraft] = useState<DiceCounts | null>(null);
  const [loadoutError, setLoadoutError] = useState<'load' | 'save' | null>(null);
  const blocked = modal !== null || (isMobile && openMobile);
  const opponent = useOpponent(state, dispatch, blocked || !ready);
  const trigger = useRef<HTMLElement | null>(null);
  const sidebarTrigger = useRef<HTMLButtonElement>(null);
  const modalTitle = useRef<HTMLHeadingElement>(null);
  const previews = useMemo(() => {
    const english = i18n.getFixedT('en', 'common');
    return [...DICE_TYPES].sort((a, b) => english(`farkle.dice.${a.id}`).localeCompare(english(`farkle.dice.${b.id}`), 'en'))
      .map((die) => ({ die, url: dicePreview(die.id).toDataURL() }));
  }, [i18n]);
  const startDisabled = !ready || !inventory || storageError !== null;
  const owned = inventory ? inventoryPool(inventory) : null;
  const ownedPreviews = previews.filter(({ die }) => owned && owned[die.id] > 0);
  const diceDialogWidth = modal === 'chooseDice' && ownedPreviews.length <= 6 ? 'sm:max-w-[480px]'
    : modal === 'chooseDice' && ownedPreviews.length <= 12 ? 'sm:max-w-[800px]' : 'sm:max-w-[1200px]';
  const selectedCount = draft ? loadoutSize(draft) : 0;
  const groups = reward ? rewardGroups(reward) : [];
  const storageAlert = storageError ? <Alert variant="destructive">
    <AlertDescription>{t(storageError === 'load' ? 'farkle.inventoryLoadError' : 'farkle.inventorySaveError')}</AlertDescription>
    <Button variant="outline" onClick={retry}>{t('farkle.retryStorage')}</Button>
  </Alert> : null;

  function prepareLoadout() {
    if (!owned) return;
    try { setDraft(readLoadout(window.localStorage, owned)); setLoadoutError(null); }
    catch { setLoadoutError('load'); }
  }

  function startGame() {
    if (startDisabled || !draft || selectedCount !== 6 || loadoutError === 'load') return;
    try { saveLoadout(window.localStorage, draft); }
    catch { setLoadoutError('save'); return; }
    setLoadoutError(null);
    const loadout = { B: loadoutDice(draft), A: drawOpponentDice(target) };
    dispatch({ type: 'start', target, loadout, values: rollValues(loadout.B) });
    setModal(null);
  }

  useEffect(() => {
    if (state.winner) {
      trigger.current = sidebarTrigger.current;
      setOpenMobile(false);
      setModal('result');
    }
  }, [state.winner, setOpenMobile]);
  useEffect(() => { if (modal) modalTitle.current?.focus(); }, [modal]);

  function openModal(kind: Modal, source: HTMLElement) {
    if (kind === 'newGame' || kind === 'chooseDice') {
      if (state.playing) setTarget(state.target);
      setDraft(null);
      setLoadoutError(null);
      prepareLoadout();
    }
    trigger.current = isMobile && source.closest('.farkle-sidebar') ? sidebarTrigger.current : source;
    setOpenMobile(false);
    setModal(kind);
  }

  return <>
    <Sidebar className="farkle-sidebar" title={t('playground.farkle')} aria-label={t('playground.farkle')}>
      <SidebarHeader className="sidebar-header shrink-0 gap-4 p-3">
        <div className="sidebar-brand">{t('appName')}</div>
        <SidebarMenu>
          <SidebarMenuItem><SidebarMenuButton onClick={(event) => openModal('newGame', event.currentTarget)}>
            <Plus /><span>{t('farkle.newGame')}</span>
          </SidebarMenuButton></SidebarMenuItem>
          <SidebarMenuItem><SidebarMenuButton onClick={(event) => openModal('myDice', event.currentTarget)}>
            <Package /><span>{t('farkle.myDice')}</span>
          </SidebarMenuButton></SidebarMenuItem>
          <SidebarMenuItem><SidebarMenuButton onClick={(event) => openModal('shop', event.currentTarget)}>
            <ShoppingBag /><span>{t('farkle.shop')}</span>
          </SidebarMenuButton></SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent />
      <SidebarFooter className="sidebar-footer shrink-0 p-3">
        <SidebarMenu><SidebarMenuItem><SidebarMenuButton disabled={storageError === 'save'} onClick={async () => {
          if (state.playing) { dispatch({ type: 'exit' }); setOpenMobile(false); }
          else if (await onNavigate(playgroundUrl())) setOpenMobile(false);
        }}>
          {state.playing ? <LogOut /> : <ArrowLeft />}<span>{t(state.playing ? 'farkle.exitGame' : 'back')}</span>
        </SidebarMenuButton></SidebarMenuItem></SidebarMenu>
      </SidebarFooter>
    </Sidebar>
    <SidebarInset className="workspace farkle-workspace min-h-0 min-w-0 overflow-hidden">
      <header className="topbar">
        <SidebarTrigger ref={sidebarTrigger} />
        <div className="settings-heading min-w-0"><h1 className="truncate">{t('playground.farkle')}</h1></div>
        <Button variant="ghost" aria-label={inventory ? t('farkle.balance', { count: inventory.merchant }) : t('farkle.myDice')}
          onClick={(event) => openModal('shop', event.currentTarget)}>
          <Coins data-icon="inline-start" /><span data-merchant-balance>{inventory?.merchant ?? '—'}</span>
        </Button>
      </header>
      {!modal && storageAlert ? <div className="p-3">{storageAlert}</div> : null}
      {state.playing && !state.winner && opponent.failed ? <div className="p-3"><Alert variant="destructive">
        <AlertDescription>{t('farkle.opponentError')}</AlertDescription>
        <AlertAction><Button variant="outline" onClick={opponent.retry}>{t('farkle.retryOpponent')}</Button></AlertAction>
      </Alert></div> : null}
      <FarkleTable state={state} dispatch={dispatch} onReady={setReady} blocked={blocked}
        onNewGame={(source) => openModal('newGame', source)} />
    </SidebarInset>
    <Dialog open={modal !== null} onOpenChange={(open) => { if (!open) setModal(null); }}>
      <DialogContent initialFocus={() => modalTitle.current}
        finalFocus={() => trigger.current?.isConnected ? trigger.current : sidebarTrigger.current}
        className={cn(modal === 'result' && 'farkle-result',
          (modal === 'myDice' || modal === 'chooseDice') && ['farkle-dice-dialog w-[calc(100%-2rem)]', diceDialogWidth])}>
        {modal === 'result' ? <div className="farkle-result-summary">
          <div className="farkle-score-heading" data-outcome={state.winner === 'B' ? 'win' : 'loss'}>
            <DialogTitle ref={modalTitle} tabIndex={-1} style={{ font: 'inherit' }}>{t(state.winner === 'B' ? 'farkle.youWin' : 'farkle.youLost')}</DialogTitle>
          </div>
          <p className="farkle-score-total" data-result-score="B">{t('farkle.resultScore', { score: state.totals.B })}</p>
        </div> : <DialogHeader>
          <DialogTitle ref={modalTitle} tabIndex={-1}>{modal ? t(`farkle.${modal}`) : ''}</DialogTitle>
          {modal === 'shop' ? <DialogDescription>{t('farkle.shopPlaceholder')}</DialogDescription> : null}
        </DialogHeader>}
        {storageAlert}
        {(modal === 'newGame' || modal === 'chooseDice') && loadoutError ? <Alert variant="destructive">
          <AlertDescription>{t(loadoutError === 'load' ? 'farkle.loadoutLoadError' : 'farkle.loadoutSaveError')}</AlertDescription>
          <Button variant="outline" disabled={startDisabled}
            onClick={loadoutError === 'load' ? prepareLoadout : startGame}>{t('farkle.retryStorage')}</Button>
        </Alert> : null}
        {modal === 'result' && state.winner ? <>
          {reward ? <div className="flex min-h-0 flex-col gap-3 overflow-y-auto" data-rewards role="group" aria-label={t('farkle.rewards')}>
            {groups.map((group, index) => <Fragment key={group.source}>
              {index > 0 ? <Separator /> : null}
              <ul className="flex shrink-0 flex-col gap-2" data-reward-group={group.source}>
                {group.entries.map(({ type, count }) => <li key={type} className="flex items-center gap-3" data-reward-type={type}>
                  <img className="size-8 shrink-0 rounded-md" src={previews.find(({ die }) => die.id === type)!.url} alt="" />
                  <span className="min-w-0 flex-1">{t(`farkle.dice.${type}`)}</span>
                  <span className="shrink-0" data-reward-count={count}>{group.source === 'regular' ? `+${count}`
                    : t(group.source === 'firstWin' ? 'farkle.firstWinAmount' : 'farkle.convertedAmount', { count })}</span>
                </li>)}
              </ul>
            </Fragment>)}
          </div> : null}
          <DialogFooter className="shrink-0">
            <Button variant="outline" onClick={(event) => openModal('newGame', event.currentTarget)}>{t('farkle.newGame')}</Button>
            <Button disabled={startDisabled} onClick={(event) => openModal('chooseDice', event.currentTarget)}>{t('farkle.playAgain')}</Button>
          </DialogFooter>
        </> : null}
        {modal === 'myDice' && inventory ? <div className="farkle-dice-list min-h-0 overflow-y-auto">
          <ul className="farkle-dice-grid">
            {previews.map(({ die, url }) => <DiceRow key={die.id} type={die.id} preview={url}
              quantity={die.category === 'special' ? `${inventory.special[die.id]} / ${SPECIAL_LIMIT}`
                : `×${die.id === 'normal' ? NORMAL_COUNT : inventory.merchant}`} />)}
          </ul>
        </div> : null}
        {modal === 'chooseDice' && owned && draft ? <>
          <p className="shrink-0" data-loadout-total aria-live="polite">{t('farkle.diceSelected', { count: selectedCount })}</p>
          <div className="farkle-dice-list min-h-0 overflow-y-auto">
            <ul className="farkle-dice-grid" data-loadout>
              {ownedPreviews.map(({ die, url }) => <DiceRow key={die.id} type={die.id} preview={url}
                quantity={`×${owned[die.id]}`} inlineQuantity>
                <div className="flex shrink-0 items-center gap-1">
                  <Button variant="outline" size="icon" aria-label={t('farkle.removeDie', { name: t(`farkle.dice.${die.id}`) })}
                    disabled={draft[die.id] === 0} onClick={() => setDraft({ ...draft, [die.id]: draft[die.id] - 1 })}><Minus /></Button>
                  <span className="w-4 text-center tabular-nums" data-selected-count>{draft[die.id]}</span>
                  <Button variant="outline" size="icon" aria-label={t('farkle.addDie', { name: t(`farkle.dice.${die.id}`) })}
                    disabled={selectedCount === 6 || draft[die.id] === owned[die.id]}
                    onClick={() => setDraft({ ...draft, [die.id]: draft[die.id] + 1 })}><Plus /></Button>
                </div>
              </DiceRow>)}
            </ul>
          </div>
          <DialogFooter className="shrink-0">
            <Button variant="outline" onClick={() => setModal('newGame')}>{t('back')}</Button>
            <Button disabled={startDisabled || selectedCount !== 6 || loadoutError === 'load'} onClick={startGame}>{t('farkle.startGame')}</Button>
          </DialogFooter>
        </> : null}
        {modal === 'newGame' ? <>
          <Field>
            <FieldLabel id="farkle-level-label">{t('farkle.level')}</FieldLabel>
            <ToggleGroup aria-labelledby="farkle-level-label" variant="outline" orientation="vertical"
              className="w-full" value={[String(target)]} onValueChange={(values) => {
                const level = LEVELS.find((item) => String(item.target) === values[0]);
                if (level) setTarget(level.target);
              }}>
              {LEVELS.map((level) => <ToggleGroupItem key={level.id} value={String(level.target)} className="justify-between">
                <span>{t(`farkle.levels.${level.id}`)}</span><span>{level.target}</span>
              </ToggleGroupItem>)}
            </ToggleGroup>
          </Field>
          <DialogFooter><Button disabled={startDisabled || loadoutError === 'load'} onClick={() => {
            if (!draft) prepareLoadout();
            setModal('chooseDice');
          }}>{t('farkle.chooseDice')}</Button></DialogFooter>
        </> : null}
      </DialogContent>
    </Dialog>
  </>;
}
