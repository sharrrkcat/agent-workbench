import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LayoutGrid, MessageSquarePlus, Plus, Settings2 } from 'lucide-react';
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarHeader, SidebarMenu, SidebarMenuButton, SidebarMenuItem, useSidebar,
} from '@/components/ui/sidebar';
import { NewCharacterDialog } from './characters/NewCharacterDialog';
import { CharactersTree } from './characters/CharactersTree';
import { characterUrl } from './characters/navigation';
import { playgroundUrl } from './playground/navigation';
import type { SettingsNavigate } from './settings/navigation';

export function SessionSidebar({ playgroundActive, resourcesCharacterId, onOpenSettings, onNavigate,
  onSelectSession, onCreateSession, onSessionDeleted, onCharacterDeleted }: {
  playgroundActive: boolean; resourcesCharacterId: string | null;
  onOpenSettings: () => Promise<boolean>; onNavigate: SettingsNavigate;
  onSelectSession: (id: string, characterId: string | null) => Promise<boolean>;
  onCreateSession: (characterId?: string | null) => Promise<boolean>;
  onSessionDeleted: (id: string) => void; onCharacterDeleted: (id: string) => void;
}) {
  const { t } = useTranslation('personas');
  const { setOpenMobile } = useSidebar();
  const [creating, setCreating] = useState(false);
  return <>
    <Sidebar className="session-sidebar" aria-label={t('characters')}>
      <SidebarHeader className="sidebar-header shrink-0 gap-4 p-3">
        <div className="sidebar-brand">{t('common:appName')}</div>
        <SidebarMenu>
          <SidebarMenuItem><SidebarMenuButton type="button" onClick={async () => {
            if (await onCreateSession()) setOpenMobile(false);
          }}><MessageSquarePlus data-icon="inline-start" /><span>{t('newSession')}</span></SidebarMenuButton></SidebarMenuItem>
          <SidebarMenuItem><SidebarMenuButton type="button" onClick={() => { setCreating(true); setOpenMobile(false); }}>
            <Plus data-icon="inline-start" /><span>{t('newCharacter')}</span></SidebarMenuButton></SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <CharactersTree resourcesCharacterId={resourcesCharacterId} onNavigate={onNavigate} onSelectSession={onSelectSession}
          onCreateSession={onCreateSession} onSessionDeleted={onSessionDeleted} onCharacterDeleted={onCharacterDeleted} />
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem><SidebarMenuButton type="button" isActive={playgroundActive} aria-current={playgroundActive ? 'page' : undefined} onClick={async () => {
            if (await onNavigate(playgroundUrl())) setOpenMobile(false);
          }}><LayoutGrid data-icon="inline-start" /><span>{t('common:playground.title')}</span></SidebarMenuButton></SidebarMenuItem>
          <SidebarMenuItem><SidebarMenuButton type="button" onClick={async () => { if (await onOpenSettings()) setOpenMobile(false); }}>
            <Settings2 data-icon="inline-start" /><span>{t('settings')}</span></SidebarMenuButton></SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
    {creating ? <NewCharacterDialog onClose={() => setCreating(false)} onNavigate={onNavigate} onSaved={(character) => {
      setCreating(false); void onNavigate(characterUrl(character.id));
    }} /> : null}
  </>;
}
