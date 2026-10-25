import { useTranslation } from 'react-i18next';
import { ArrowLeft, AudioLines, Dice5, type LucideIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyContent, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { SidebarTrigger } from '@/components/ui/sidebar';
import type { SettingsNavigate } from '../settings/navigation';
import { playgroundUrl, type PlaygroundRoute } from './navigation';

function AppCard({ name, icon: Icon, disabled = false, onOpen }: {
  name: string; icon: LucideIcon; disabled?: boolean; onOpen?: () => void;
}) {
  return <Card className="relative min-h-40 justify-center has-disabled:opacity-50">
    <CardHeader className="justify-items-center gap-3">
      <div className="flex size-10 items-center justify-center [&>svg]:size-8"><Icon aria-hidden="true" /></div>
      <CardTitle>{name}</CardTitle>
    </CardHeader>
    <Button type="button" variant="ghost" className="absolute inset-0 h-full w-full rounded-lg"
      aria-label={name} disabled={disabled} onClick={onOpen} />
  </Card>;
}

export function PlaygroundPage({ route, onNavigate }: { route: PlaygroundRoute; onNavigate: SettingsNavigate }) {
  const { t } = useTranslation('common');
  const farkle = route === 'farkle';
  return <>
    <header className="settings-header">
      <SidebarTrigger />
      <div className="settings-heading min-w-0"><h1 className="truncate">{t(farkle ? 'playground.farkle' : 'playground.title')}</h1></div>
    </header>
    <div className="settings-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain">
      <div className="settings-content">
        {farkle ? <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon"><Dice5 aria-hidden="true" /></EmptyMedia>
            <EmptyTitle>{t('playground.comingSoon')}</EmptyTitle>
          </EmptyHeader>
          <EmptyContent>
            <Button variant="outline" onClick={() => void onNavigate(playgroundUrl())}>
              <ArrowLeft data-icon="inline-start" />{t('playground.back')}
            </Button>
          </EmptyContent>
        </Empty> : <div className="@container">
          <div className="grid grid-cols-1 gap-4 @min-[640px]:grid-cols-2">
            <AppCard name={t('playground.farkle')} icon={Dice5} onOpen={() => void onNavigate(playgroundUrl('farkle'))} />
            <AppCard name={t('playground.whisper')} icon={AudioLines} disabled />
          </div>
        </div>}
      </div>
    </div>
  </>;
}
