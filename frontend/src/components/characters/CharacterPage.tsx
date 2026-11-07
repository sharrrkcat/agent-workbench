import { useTranslation } from 'react-i18next';
import { SidebarTrigger } from '@/components/ui/sidebar';
import { useCharactersStore } from '../../store/useCharactersStore';
import { useCogitaStore } from '../../store/useCogitaStore';
import { CharacterEditor } from './CharacterEditor';
import { CharacterSettings } from './CharacterSettings';
import { ResourceLoading, type LeaveGuard } from '../settings/resources/ResourceUI';
import type { SettingsNavigate } from '../settings/navigation';
import { ErrorBanner } from '../ErrorBanner';

export function CharacterPage({ characterId, onNavigate, onLeaveGuardChange }: {
  characterId: string; onNavigate: SettingsNavigate; onLeaveGuardChange: (guard: LeaveGuard) => void;
}) {
  const { t } = useTranslation('personas');
  const character = useCharactersStore((state) => state.characters.find((p) => p.id === characterId));
  const error = useCogitaStore((state) => state.error);
  return <>
    <header className="settings-header">
      <SidebarTrigger />
      <div className="settings-heading min-w-0"><h1 className="truncate">{character?.name || t('characterSettings')}</h1></div>
    </header>
    <ErrorBanner />
    <div className="settings-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain">
      <div className="settings-content">
        {character?.kind === 'normal' ? <CharacterSettings key={character.id} character={character} onLeaveGuardChange={onLeaveGuardChange} /> :
          character ? <CharacterEditor key={character.id} character={character} kind={character.kind} onSaved={() => undefined}
          onNavigate={onNavigate} onLeaveGuardChange={onLeaveGuardChange} /> :
          <ResourceLoading error={error || undefined} retry={() => void useCharactersStore.getState().load(characterId)} />}
      </div>
    </div>
  </>;
}
