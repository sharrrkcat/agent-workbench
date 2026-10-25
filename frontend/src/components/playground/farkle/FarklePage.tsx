import { useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, Coins, LogOut, Package, Plus, ShoppingBag, View } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Field, FieldLabel } from '@/components/ui/field';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Sidebar, SidebarContent, SidebarFooter, SidebarHeader, SidebarInset, SidebarMenu,
  SidebarMenuButton, SidebarMenuItem, SidebarTrigger, useSidebar } from '@/components/ui/sidebar';
import type { SettingsNavigate } from '@/components/settings/navigation';
import { playgroundUrl } from '../navigation';
import { FarkleTable } from './FarkleTable';
import { DICE_SKINS, faceCanvas } from './materials';
import { gameReducer, initialGame, LEVELS, randomValues, type TargetScore } from './state';

type Modal = 'newGame' | 'myDice' | 'shop' | 'result';

export default function FarklePage({ onNavigate }: { onNavigate: SettingsNavigate }) {
  const { t } = useTranslation('common');
  const { setOpenMobile, isMobile, openMobile } = useSidebar();
  const [state, dispatch] = useReducer(gameReducer, initialGame);
  const [modal, setModal] = useState<Modal | null>(null);
  const [ready, setReady] = useState(false);
  const [target, setTarget] = useState<TargetScore>(1500);
  const trigger = useRef<HTMLElement | null>(null);
  const sidebarTrigger = useRef<HTMLButtonElement>(null);
  const previews = useMemo(() => DICE_SKINS.map((skin) => ({ skin, url: faceCanvas(skin, 1).toDataURL() })), []);

  useEffect(() => {
    if (state.winner) {
      trigger.current = sidebarTrigger.current;
      setOpenMobile(false);
      setModal('result');
    }
  }, [state.winner, setOpenMobile]);

  function openModal(kind: Modal, source: HTMLElement) {
    if (kind === 'newGame' && state.playing) setTarget(state.target);
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
          <SidebarMenuItem><SidebarMenuButton disabled={!ready || !state.playing || state.busy || !!state.winner}
            onClick={() => { setOpenMobile(false); dispatch({ type: 'switch' }); }}>
            <View /><span>{t('farkle.switchView')}</span>
          </SidebarMenuButton></SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent />
      <SidebarFooter className="sidebar-footer shrink-0 p-3">
        <SidebarMenu><SidebarMenuItem><SidebarMenuButton onClick={async () => {
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
        <Button variant="ghost" aria-label={t('farkle.balance', { count: 100 })} onClick={(event) => openModal('shop', event.currentTarget)}>
          <Coins data-icon="inline-start" /><span>100</span>
        </Button>
      </header>
      <FarkleTable state={state} dispatch={dispatch} onReady={setReady} blocked={modal !== null || (isMobile && openMobile)} />
    </SidebarInset>
    <Dialog open={modal !== null} onOpenChange={(open) => { if (!open) setModal(null); }}>
      <DialogContent finalFocus={() => trigger.current}>
        <DialogHeader>
          <DialogTitle>{modal ? t(`farkle.${modal}`) : ''}</DialogTitle>
          {modal === 'shop' ? <DialogDescription>{t('farkle.shopPlaceholder')}</DialogDescription> : null}
        </DialogHeader>
        {modal === 'result' && state.winner ? <>
          <p>{t('farkle.winner', { player: t(state.winner === 'B' ? 'farkle.player' : 'farkle.opponent') })}</p>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
            <dt>{t('farkle.player')}</dt><dd className="text-right" data-result-score="B">{state.totals.B}</dd>
            <dt>{t('farkle.opponent')}</dt><dd className="text-right" data-result-score="A">{state.totals.A}</dd>
          </dl>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setTarget(state.target); setModal('newGame'); }}>{t('farkle.newGame')}</Button>
            <Button disabled={!ready} onClick={() => {
              dispatch({ type: 'start', target: state.target, values: randomValues() }); setModal(null);
            }}>{t('farkle.playAgain')}</Button>
          </DialogFooter>
        </> : null}
        {modal === 'myDice' ? <ul className="flex min-h-0 flex-col gap-3 overflow-y-auto">
          {previews.map(({ skin, url }) => <li key={skin.id} className="flex items-center gap-3">
            <img className="size-10 rounded-md" src={url} alt="" />
            <span className="flex-1">{t(`farkle.skins.${skin.id}`)}</span>
            <span aria-label={t('farkle.quantity', { count: 1 })}>×1</span>
          </li>)}
        </ul> : null}
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
          <DialogFooter><Button disabled={!ready} onClick={() => {
            dispatch({ type: 'start', target, values: randomValues() }); setModal(null);
          }}>{t('farkle.startGame')}</Button></DialogFooter>
        </> : null}
      </DialogContent>
    </Dialog>
  </>;
}
