import { Fragment, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, Coins, LogOut, Package, Plus, RotateCcw, Settings, ShoppingBag, SlidersHorizontal } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Alert, AlertAction, AlertDescription } from '@/components/ui/alert';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Separator } from '@/components/ui/separator';
import { cn } from '@/lib/utils';
import { changeLocale, type SupportedLocale } from '@/i18n/index';
import { Sidebar, SidebarContent, SidebarFooter, SidebarHeader, SidebarInset, SidebarMenu,
  SidebarMenuButton, SidebarMenuItem, SidebarTrigger, useSidebar } from '@/components/ui/sidebar';
import type { SettingsNavigate } from '@/components/settings/navigation';
import { playgroundUrl } from '../navigation';
import { FarkleTable } from './FarkleTable';
import { dicePreview } from './materials';
import { DICE_TYPES, rollValues, SPECIAL_LIMIT, type DiceCounts } from './dice';
import { drawOpponentDice, OPPONENT_DICE_MODES, type OpponentDiceMode } from './opponentDice';
import { canModifyInventory, DICE_BUY_PRICE, DICE_SELL_PRICE, inventoryPool, INVENTORY_ACTIONS, LEVELS, type LevelId } from './economy';
import { gameReducer, initialGame } from './state';
import { useInventory } from './useInventory';
import { rewardGroups } from './rewards';
import { defaultLoadout, FULL_DICE_POOL, loadoutDice, randomLoadout, readLoadout, saveLoadout } from './loadout';
import { DiceRow } from './DiceRow';
import { DiceChooser } from './DiceChooser';
import { DiceShop } from './DiceShop';
import { CUSTOM_OPPONENT_MODES, defaultCustomGame, matchTarget, targetError, readCustomGame,
  saveCustomGame, type CustomGame, type MatchSetup } from './customGame';
import { useOpponent } from './useOpponent';
import { useFarkleSettings } from './useFarkleSettings';
import { clearFarkleStorage } from './storage';

type Modal = 'newGame' | 'customGame' | 'chooseDice' | 'chooseOpponentDice' | 'choosePlayerDice' | 'myDice' | 'shop' | 'settings' | 'result';

export default function FarklePage({ onNavigate }: { onNavigate: SettingsNavigate }) {
  const { t, i18n } = useTranslation('common');
  const { setOpenMobile, isMobile, openMobile } = useSidebar();
  const [state, dispatch] = useReducer(gameReducer, initialGame);
  const collection = useInventory(state.winner, state.setup?.kind === 'standard' ? state.setup.level : null);
  const { inventory, reward, error: storageError, retry } = collection;
  const settings = useFarkleSettings();
  const [localeError, setLocaleError] = useState<SupportedLocale | null>(null);
  const [clearError, setClearError] = useState(false);
  const [modal, setModal] = useState<Modal | null>(null);
  const [ready, setReady] = useState(false);
  const [level, setLevel] = useState<LevelId>('beggars');
  const [custom, setCustom] = useState(defaultCustomGame);
  const [targetText, setTargetText] = useState('1500');
  const [customError, setCustomError] = useState<'load' | 'save' | null>(null);
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
  const inventoryPreviews = useMemo(() => {
    if (modal !== 'myDice' || !inventory) return [];
    const counts = inventoryPool(inventory);
    return previews.map(({ die }) => ({ die, count: counts[die.id],
      url: dicePreview(die.id, Math.min(6, counts[die.id]) || 5).toDataURL() }));
  }, [inventory, modal, previews]);
  const startDisabled = !ready || !inventory || storageError !== null || clearError;
  const owned = inventory ? inventoryPool(inventory) : null;
  const ownedPreviews = previews.filter(({ die }) => owned && owned[die.id] > 0);
  const playerChooser = modal === 'chooseDice' || modal === 'choosePlayerDice';
  const customFlow = modal === 'customGame' || modal === 'chooseOpponentDice' || modal === 'choosePlayerDice';
  const diceDialogWidth = modal === 'chooseDice' && ownedPreviews.length <= 6 ? 'sm:max-w-[480px]'
    : modal === 'chooseDice' && ownedPreviews.length <= 12 ? 'sm:max-w-[800px]' : 'sm:max-w-[1200px]';
  const scoreError = targetError(targetText);
  const customTarget = scoreError ? null : Number(targetText);
  const groups = reward ? rewardGroups(reward) : [];
  const storageAlert = storageError ? <Alert variant="destructive">
    <AlertDescription>{t(storageError === 'load' ? 'farkle.inventoryLoadError' : 'farkle.inventorySaveError')}</AlertDescription>
    <Button variant="outline" onClick={retry}>{t('farkle.retryStorage')}</Button>
  </Alert> : null;
  const clearAlert = clearError ? <Alert variant="destructive">
    <AlertDescription>{t('farkle.clearCacheError')}</AlertDescription>
    <Button variant="outline" onClick={clearCache}>{t('farkle.retryStorage')}</Button>
  </Alert> : null;

  async function setLanguage(locale: SupportedLocale) {
    try { await changeLocale(locale); setLocaleError(null); }
    catch { setLocaleError(locale); }
  }

  function clearCache() {
    try { clearFarkleStorage(window.localStorage); }
    catch { setClearError(true); return; }
    dispatch({ type: 'exit' });
    collection.reset();
    settings.reset();
    setClearError(false);
    setLevel('beggars');
    setCustom(defaultCustomGame());
    setTargetText('1500');
    setCustomError(null);
    setDraft(null);
    setLoadoutError(null);
    setModal(null);
    setOpenMobile(false);
  }

  function prepareLoadout() {
    if (!owned) return;
    try { setDraft(readLoadout(window.localStorage, owned)); setLoadoutError(null); }
    catch { setLoadoutError('load'); }
  }

  function prepareCustom(config?: CustomGame) {
    try {
      const next = config ?? readCustomGame(window.localStorage);
      setCustom(next); setTargetText(String(next.target)); setCustomError(null);
    } catch { setCustomError('load'); }
  }

  function updatePlayerLoadout(counts: DiceCounts) {
    if (customFlow) setCustom({ ...custom, playerLoadout: counts });
    else setDraft(counts);
  }

  function startGame() {
    if (startDisabled || (!customFlow && (!draft || loadoutError === 'load'))
      || (customFlow && (customTarget === null || customError === 'load'))) return;
    const setup: MatchSetup = customFlow ? { kind: 'custom', config: { ...custom, target: customTarget! } }
      : { kind: 'standard', level };
    if (setup.kind === 'custom') {
      try { saveCustomGame(window.localStorage, setup.config); }
      catch { setCustomError('save'); return; }
    } else {
      try { saveLoadout(window.localStorage, draft!); }
      catch { setLoadoutError('save'); return; }
      setLoadoutError(null);
    }
    setCustomError(null);
    const target = matchTarget(setup);
    const mode = setup.kind === 'custom' ? setup.config.opponentDiceMode : settings.mode;
    const loadout = { B: loadoutDice(setup.kind === 'custom' ? setup.config.playerLoadout : draft!), A: mode === 'custom'
      ? loadoutDice(custom.opponentLoadout) : drawOpponentDice(target, mode) };
    dispatch({ type: 'start', setup, loadout, values: rollValues(loadout.B) });
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
      if (state.setup?.kind === 'standard') setLevel(state.setup.level);
      setDraft(null);
      setLoadoutError(null);
      prepareLoadout();
    }
    if (kind === 'customGame') prepareCustom();
    if ((kind === 'chooseOpponentDice' || kind === 'choosePlayerDice') && state.setup?.kind === 'custom') {
      prepareCustom(state.setup.config);
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
          <SidebarMenuItem><SidebarMenuButton onClick={(event) => openModal('customGame', event.currentTarget)}>
            <SlidersHorizontal /><span>{t('farkle.customGame')}</span>
          </SidebarMenuButton></SidebarMenuItem>
          <SidebarMenuItem><SidebarMenuButton onClick={(event) => openModal('myDice', event.currentTarget)}>
            <Package /><span>{t('farkle.myDice')}</span>
          </SidebarMenuButton></SidebarMenuItem>
          <SidebarMenuItem><SidebarMenuButton onClick={(event) => openModal('shop', event.currentTarget)}>
            <ShoppingBag /><span>{t('farkle.shop')}</span>
          </SidebarMenuButton></SidebarMenuItem>
          <SidebarMenuItem><SidebarMenuButton onClick={(event) => openModal('settings', event.currentTarget)}>
            <Settings /><span>{t('farkle.settings')}</span>
          </SidebarMenuButton></SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent />
      <SidebarFooter className="sidebar-footer shrink-0 p-3">
        <SidebarMenu><SidebarMenuItem><SidebarMenuButton disabled={storageError === 'save' || clearError} onClick={async () => {
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
      {!modal && clearAlert ? <div className="p-3">{clearAlert}</div> : null}
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
          (modal === 'myDice' || modal === 'shop' || playerChooser || modal === 'chooseOpponentDice')
            && ['farkle-dice-dialog w-[calc(100%-2rem)]', diceDialogWidth])}>
        {modal === 'result' ? <div className="farkle-result-summary">
          <div className="farkle-score-heading" data-outcome={state.winner === 'B' ? 'win' : 'loss'}>
            <DialogTitle ref={modalTitle} tabIndex={-1} style={{ font: 'inherit' }}>{t(state.winner === 'B' ? 'farkle.youWin' : 'farkle.youLost')}</DialogTitle>
          </div>
          <p className="farkle-score-total" data-result-score="B">{t('farkle.resultScore', { score: state.totals.B })}</p>
        </div> : <DialogHeader>
          <div className="flex items-center gap-3 pr-6">
            <DialogTitle ref={modalTitle} tabIndex={-1}>{modal ? t(`farkle.${modal}`) : ''}</DialogTitle>
            {playerChooser || modal === 'chooseOpponentDice' ? <Button variant="ghost" size="icon"
              aria-label={t('farkle.resetDice')} title={t('farkle.resetDice')}
              disabled={customFlow ? customError === 'load' : !draft || !owned || loadoutError === 'load'}
              onClick={() => modal === 'chooseOpponentDice'
                ? setCustom({ ...custom, opponentLoadout: defaultLoadout() }) : updatePlayerLoadout(defaultLoadout())}>
              <RotateCcw />
            </Button> : null}
            {modal === 'shop' ? <span className="inline-flex items-center gap-1 text-sm text-muted-foreground tabular-nums"
              data-shop-balance aria-label={inventory ? t('farkle.balance', { count: inventory.merchant }) : undefined}>
              <Coins className="size-4" /><span>{inventory?.merchant ?? '—'}</span>
            </span> : null}
          </div>
          {modal === 'shop' ? <DialogDescription data-shop-prices>
            {t('farkle.shopPrices', { buy: DICE_BUY_PRICE, sell: DICE_SELL_PRICE })}
          </DialogDescription> : null}
        </DialogHeader>}
        {modal !== 'settings' ? <>{storageAlert}{clearAlert}</> : null}
        {modal === 'settings' ? <FieldGroup className="min-h-0 overflow-y-auto">
          {storageAlert}{clearAlert}
          <Field>
            <FieldLabel id="farkle-language-label">{t('language')}</FieldLabel>
            <ToggleGroup aria-labelledby="farkle-language-label" variant="segmented" value={[i18n.language]}
              onValueChange={(values) => { if (values.length) void setLanguage(values[0] as SupportedLocale); }}>
              <ToggleGroupItem value="en">English</ToggleGroupItem>
              <ToggleGroupItem value="zh-CN">简体中文</ToggleGroupItem>
            </ToggleGroup>
            {localeError ? <Alert variant="destructive">
              <AlertDescription>{t('farkle.languageSaveError')}</AlertDescription>
              <Button variant="outline" onClick={() => void setLanguage(localeError)}>{t('farkle.retryStorage')}</Button>
            </Alert> : null}
          </Field>
          <Field>
            <FieldLabel id="farkle-opponent-dice-label">{t('farkle.opponentDice')}</FieldLabel>
            <ToggleGroup aria-labelledby="farkle-opponent-dice-label" aria-describedby="farkle-opponent-dice-hint"
              variant="segmented" value={[settings.mode]} disabled={settings.error === 'load'}
              onValueChange={(values) => { if (values.length) settings.setMode(values[0] as OpponentDiceMode); }}>
              {OPPONENT_DICE_MODES.map((mode) => <ToggleGroupItem key={mode} value={mode}>
                {t(`farkle.opponentModes.${mode}`)}
              </ToggleGroupItem>)}
            </ToggleGroup>
            <FieldDescription id="farkle-opponent-dice-hint" aria-live="polite">
              {t(`farkle.opponentModeHints.${settings.mode}`)}
            </FieldDescription>
          </Field>
          {settings.error ? <Alert variant="destructive">
            <AlertDescription>{t(settings.error === 'load' ? 'farkle.settingsLoadError' : 'farkle.settingsSaveError')}</AlertDescription>
            <Button variant="outline" onClick={settings.retry}>{t('farkle.retryStorage')}</Button>
          </Alert> : null}
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2" data-inventory-actions>
            {INVENTORY_ACTIONS.map((action) => <Button key={action} variant="outline"
              disabled={!inventory || storageError !== null || clearError || !canModifyInventory(inventory, action)}
              onClick={() => collection.modify(action)}>{t(`farkle.${action}`)}</Button>)}
          </div>
          <Separator />
          <Field>
            <Button variant="destructive" aria-describedby="farkle-clear-cache-hint" onClick={clearCache}>
              {t('farkle.clearCache')}
            </Button>
            <FieldDescription id="farkle-clear-cache-hint">{t('farkle.clearCacheHint')}</FieldDescription>
          </Field>
        </FieldGroup> : null}
        {(modal === 'newGame' || modal === 'chooseDice') && loadoutError ? <Alert variant="destructive">
          <AlertDescription>{t(loadoutError === 'load' ? 'farkle.loadoutLoadError' : 'farkle.loadoutSaveError')}</AlertDescription>
          <Button variant="outline" disabled={startDisabled}
            onClick={loadoutError === 'load' ? prepareLoadout : startGame}>{t('farkle.retryStorage')}</Button>
        </Alert> : null}
        {customFlow && customError ? <Alert variant="destructive">
          <AlertDescription>{t(customError === 'load' ? 'farkle.customLoadError' : 'farkle.customSaveError')}</AlertDescription>
          <Button variant="outline" disabled={startDisabled}
            onClick={customError === 'load' ? () => prepareCustom() : startGame}>{t('farkle.retryStorage')}</Button>
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
            <Button disabled={startDisabled} onClick={(event) => openModal(state.setup?.kind === 'custom'
              ? state.setup.config.opponentDiceMode === 'custom' ? 'chooseOpponentDice' : 'choosePlayerDice'
              : 'chooseDice', event.currentTarget)}>{t('farkle.playAgain')}</Button>
          </DialogFooter>
        </> : null}
        {modal === 'myDice' && inventory ? <div className="farkle-dice-list min-h-0 overflow-y-auto">
          <ul className="farkle-dice-grid">
            {inventoryPreviews.map(({ die, url, count }) => <DiceRow key={die.id} type={die.id} preview={url} unowned={count === 0}
              quantity={`${count} / ${die.id === 'merchant' ? '∞' : SPECIAL_LIMIT}`} />)}
          </ul>
        </div> : null}
        {modal === 'shop' && inventory ? <DiceShop inventory={inventory} previews={previews}
          disabled={storageError !== null || clearError} onTrade={collection.trade} /> : null}
        {playerChooser && (customFlow || (owned && draft)) ? <>
          <DiceChooser counts={customFlow ? custom.playerLoadout : draft!} available={customFlow ? FULL_DICE_POOL : owned!}
            previews={previews} showInventory={!customFlow}
            onChange={updatePlayerLoadout} />
          <DialogFooter className="shrink-0">
            <div className="flex gap-2 max-sm:*:flex-1">
              <Button variant="outline" onClick={() => setModal(modal === 'chooseDice' ? 'newGame'
                : custom.opponentDiceMode === 'custom' ? 'chooseOpponentDice' : 'customGame')}>{t('back')}</Button>
              <Button variant="outline" disabled={customFlow ? customError === 'load' : loadoutError === 'load'}
                onClick={() => updatePlayerLoadout(randomLoadout(customFlow ? FULL_DICE_POOL : owned!))}>
                {t('farkle.randomDice')}
              </Button>
            </div>
            <Button disabled={startDisabled || (customFlow ? customError === 'load' : loadoutError === 'load')}
              onClick={startGame}>{t('farkle.startGame')}</Button>
          </DialogFooter>
        </> : null}
        {modal === 'chooseOpponentDice' ? <>
          <DiceChooser counts={custom.opponentLoadout} available={FULL_DICE_POOL} previews={previews} showInventory={false}
            onChange={(opponentLoadout) => setCustom({ ...custom, opponentLoadout })} />
          <DialogFooter className="shrink-0">
            <Button variant="outline" onClick={() => setModal('customGame')}>{t('back')}</Button>
            <Button disabled={startDisabled || customError === 'load'}
              onClick={() => setModal('choosePlayerDice')}>{t('farkle.choosePlayerDice')}</Button>
          </DialogFooter>
        </> : null}
        {modal === 'customGame' ? <>
          <FieldGroup>
            <Field data-invalid={customTarget === null || undefined}>
              <FieldLabel htmlFor="farkle-custom-target">{t('farkle.targetScore')}</FieldLabel>
              <Input id="farkle-custom-target" inputMode="numeric" required pattern="[0-9]+" value={targetText}
                disabled={customError === 'load'} aria-invalid={customTarget === null}
                aria-describedby={customTarget === null ? 'farkle-target-error' : undefined}
                onChange={(event) => setTargetText(event.target.value)} />
              {scoreError ? <FieldError id="farkle-target-error">{t(`farkle.targetErrors.${scoreError}`)}</FieldError> : null}
            </Field>
            <Field>
              <FieldLabel id="farkle-custom-mode-label">{t('farkle.opponentDice')}</FieldLabel>
              <ToggleGroup aria-labelledby="farkle-custom-mode-label" aria-describedby="farkle-custom-mode-hint"
                variant="segmented" value={[custom.opponentDiceMode]}
                disabled={customError === 'load'} onValueChange={(values) => {
                  if (values.length) setCustom({ ...custom, opponentDiceMode: values[0] as CustomGame['opponentDiceMode'] });
                }}>
                {CUSTOM_OPPONENT_MODES.map((mode) => <ToggleGroupItem key={mode} value={mode}>
                  {t(`farkle.opponentModes.${mode}`)}
                </ToggleGroupItem>)}
              </ToggleGroup>
              <FieldDescription id="farkle-custom-mode-hint" aria-live="polite">
                {t(`farkle.opponentModeHints.${custom.opponentDiceMode}`)}
              </FieldDescription>
            </Field>
          </FieldGroup>
          <DialogFooter><Button disabled={startDisabled || customTarget === null || customError === 'load'}
            onClick={() => setModal(custom.opponentDiceMode === 'custom' ? 'chooseOpponentDice' : 'choosePlayerDice')}>
            {t(custom.opponentDiceMode === 'custom' ? 'farkle.chooseOpponentDice' : 'farkle.choosePlayerDice')}
          </Button></DialogFooter>
        </> : null}
        {modal === 'newGame' ? <>
          <Field className="min-h-0">
            <FieldLabel id="farkle-level-label">{t('farkle.level')}</FieldLabel>
            <ToggleGroup aria-labelledby="farkle-level-label" variant="outline" orientation="vertical"
              className="min-h-0 w-full overflow-y-auto" value={[level]} onValueChange={(values) => {
                if (values.length) setLevel(values[0] as LevelId);
              }}>
              {LEVELS.map((level) => <ToggleGroupItem key={level.id} value={level.id} className="shrink-0 justify-between">
                <span>{t(`farkle.levels.${level.id}`)}</span><span>{level.target}</span>
              </ToggleGroupItem>)}
            </ToggleGroup>
          </Field>
          <DialogFooter className="shrink-0"><Button disabled={startDisabled || loadoutError === 'load'} onClick={() => {
            if (!draft) prepareLoadout();
            setModal('chooseDice');
          }}>{t('farkle.chooseDice')}</Button></DialogFooter>
        </> : null}
      </DialogContent>
    </Dialog>
  </>;
}
