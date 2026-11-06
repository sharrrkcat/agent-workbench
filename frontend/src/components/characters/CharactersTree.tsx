import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Bot, MessageCircle, MessageSquarePlus, MoreHorizontal, Settings2, Trash2 } from 'lucide-react';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Empty, EmptyDescription } from '@/components/ui/empty';
import { SidebarGroup, SidebarGroupLabel, SidebarMenu, SidebarMenuAction, SidebarMenuButton, SidebarMenuItem,
  SidebarMenuSub, SidebarMenuSubButton, SidebarMenuSubItem, useSidebar } from '@/components/ui/sidebar';
import { DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { cn } from '@/lib/utils';
import { useCharactersStore } from '../../store/useCharactersStore';
import { useCogitaStore } from '../../store/useCogitaStore';
import type { Character } from '../../types/characters';
import type { SettingsNavigate } from '../settings/navigation';
import { ResourceLoading, errorText } from '../settings/resources/ResourceUI';
import { characterUrl, characterSettingsUrl, characterResourcesUrl } from './navigation';

type TreeActions = {
  resourcesCharacterId: string | null;
  onNavigate: SettingsNavigate;
  onSelectSession: (id: string, characterId: string | null) => Promise<boolean>;
  onCreateSession: (characterId?: string | null) => Promise<boolean>;
  onSessionDeleted: (id: string) => void;
  onCharacterDeleted: (id: string) => void;
};

export function CharactersTree(props: TreeActions) {
  const { t } = useTranslation('personas');
  const characters = useCharactersStore((state) => state.characters);
  return <SidebarGroup>
    <SidebarGroupLabel>{t('characters')}</SidebarGroupLabel>
    <SidebarMenu>
      {[...characters].sort((a, b) => Number(b.is_protected) - Number(a.is_protected)).map((character) => <CharacterItem key={character.id} character={character} {...props} />)}
    </SidebarMenu>
    {!characters.length ? <Empty className="items-start px-2 py-1 text-left"><EmptyDescription>{t('noCharacters')}</EmptyDescription></Empty> : null}
  </SidebarGroup>;
}

function CharacterItem({ character, resourcesCharacterId, onNavigate, onSelectSession, onCreateSession, onSessionDeleted, onCharacterDeleted }: TreeActions & { character: Character }) {
  const { t } = useTranslation('personas');
  const { confirm, confirmation } = useConfirmDialog();
  const { setOpenMobile } = useSidebar();
  const currentCharacterId = useCogitaStore((state) => state.currentCharacterId);
  const current = useCogitaStore((state) => state.currentSession);
  const targetId = useCogitaStore((state) => state.sessionLoad?.sessionId);
  const allSessions = useCogitaStore((state) => state.sessions);
  const reloadSessions = useCogitaStore((state) => state.reloadSessions);
  const [expanded, setExpanded] = useState(currentCharacterId === character.id);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const [deleting, setDeleting] = useState<string | null>(null);
  const sessions = allSessions.filter((session) => session.character_id === character.id);
  const active = currentCharacterId === character.id;
  useEffect(() => { if (active) setExpanded(true); }, [active]);
  useEffect(() => {
    if (!expanded) return;
    let live = true;
    setLoading(true); setError('');
    void reloadSessions(character.id).catch((reason) => { if (live) setError(errorText(reason)); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [expanded, character.id, character.kind, reload, reloadSessions]);
  const openSettings = async () => { if (await onNavigate(characterSettingsUrl(character.id))) setOpenMobile(false); };
  async function deleteCharacter() {
    if (!(await confirm(t('deleteCharacterConfirm', { name: character.name }), { destructive: true }))) return;
    setDeleting(character.id);
    try {
      await useCharactersStore.getState().remove(character.id);
      useCogitaStore.getState().forgetCharacter(character.id);
      onCharacterDeleted(character.id);
    } catch (reason) { useCogitaStore.getState().setError(errorText(reason)); setDeleting(null); }
  }
  async function deleteSession(id: string) {
    if (!(await confirm(t('deleteSessionConfirm'), { destructive: true }))) return;
    setDeleting(id);
    await useCogitaStore.getState().deleteSession(id);
    if (!useCogitaStore.getState().sessions.some((session) => session.session_id === id)) onSessionDeleted(id);
    setDeleting(null);
  }
  const Icon = character.kind === 'qqbot' ? Bot : MessageCircle;
  return <SidebarMenuItem data-character-id={character.id}>
    <Collapsible open={expanded}>
      <div className="group/character-heading relative flex items-center">
        <CollapsibleTrigger render={<SidebarMenuButton type="button" className="character-select pr-14 pointer-coarse:pr-22"
          isActive={active} title={character.name} disabled={deleting === character.id} />}
          onClick={async () => {
            if (active) { setExpanded(!expanded); return; }
            if (await onNavigate(characterUrl(character.id))) { setExpanded(true); setOpenMobile(false); }
          }}>
          <Icon data-icon="inline-start" /><span>{character.name}</span>
        </CollapsibleTrigger>
        <SidebarMenuAction type="button" aria-label={t('newCharacterSession', { name: character.name })}
          title={t('newSession')} className="right-7 opacity-0 group-hover/character-heading:opacity-100 group-has-[:focus-visible]/character-heading:opacity-100 pointer-coarse:right-11 pointer-coarse:opacity-100"
          onClick={async () => { if (await onCreateSession(character.id)) { setExpanded(true); setOpenMobile(false); } }}>
          <MessageSquarePlus />
        </SidebarMenuAction>
        <DropdownMenu>
          <DropdownMenuTrigger render={<SidebarMenuAction type="button" aria-label={t('characterActions', { name: character.name })} />}><MoreHorizontal /></DropdownMenuTrigger>
          <DropdownMenuContent align="end"><DropdownMenuGroup>
            <DropdownMenuItem onClick={() => void openSettings()}><Settings2 data-icon="inline-start" />{t('characterSettings')}</DropdownMenuItem>
            {!character.is_protected ? <DropdownMenuItem variant="destructive" disabled={!!deleting} onClick={() => void deleteCharacter()}><Trash2 data-icon="inline-start" />{t('deleteCharacter')}</DropdownMenuItem> : null}
          </DropdownMenuGroup></DropdownMenuContent>
        </DropdownMenu>
      </div>
      <CollapsibleContent>
        <SidebarMenuSub className="mr-0 translate-x-0 pr-0">
          {character.kind === 'qqbot' ? <SidebarMenuSubItem className={cn('session-item', resourcesCharacterId === character.id && 'selected')}>
            <SidebarMenuSubButton render={<button type="button" />} className="session-select w-full translate-x-0 pointer-coarse:min-h-11"
              isActive={resourcesCharacterId === character.id} aria-current={resourcesCharacterId === character.id ? 'page' : undefined}
              onClick={async () => { if (await onNavigate(characterResourcesUrl(character.id))) setOpenMobile(false); }}>
              <span>{t('qq.resources.title')}</span>
            </SidebarMenuSubButton>
          </SidebarMenuSubItem> : null}
          {sessions.map((session) => {
            const title = session.title.trim() || t('newSession');
            const selected = (targetId ?? current?.session_id) === session.session_id;
            return <SidebarMenuSubItem key={session.session_id} className={cn('session-item', selected && 'selected')}>
              <SidebarMenuSubButton render={<button type="button" disabled={deleting === session.session_id} />}
                className="session-select w-full translate-x-0 pr-8 pointer-coarse:min-h-11 pointer-coarse:pr-11" isActive={selected} aria-current={selected ? 'page' : undefined} title={title}
                onClick={async () => { if (await onSelectSession(session.session_id, character.id)) setOpenMobile(false); }}><span>{title}</span></SidebarMenuSubButton>
              <DropdownMenu>
                <DropdownMenuTrigger render={<SidebarMenuAction type="button"
                  className="session-menu top-0.5 opacity-0 group-hover/menu-sub-item:opacity-100 group-has-[:focus-visible]/menu-sub-item:opacity-100 aria-expanded:opacity-100 pointer-coarse:opacity-100"
                  aria-label={t('sessionActions', { title })} />}><MoreHorizontal /></DropdownMenuTrigger>
                <DropdownMenuContent align="end"><DropdownMenuGroup>
                  <DropdownMenuItem variant="destructive" disabled={!!deleting} onClick={() => void deleteSession(session.session_id)}>
                    <Trash2 data-icon="inline-start" />{t('deleteSession')}
                  </DropdownMenuItem>
                </DropdownMenuGroup></DropdownMenuContent>
              </DropdownMenu>
            </SidebarMenuSubItem>;
          })}
          {(loading && !sessions.length) || error ? <SidebarMenuSubItem><ResourceLoading error={error} retry={() => setReload((n) => n + 1)} /></SidebarMenuSubItem> : null}
          {!loading && !error && !sessions.length ? <SidebarMenuSubItem><Empty className="items-start px-2 py-1 text-left">
            <EmptyDescription>{t(character.kind === 'qqbot' ? 'qq.emptyConversations' : 'noCharacterSessions')}</EmptyDescription>
          </Empty></SidebarMenuSubItem> : null}
        </SidebarMenuSub>
      </CollapsibleContent>
    </Collapsible>
    {confirmation}
  </SidebarMenuItem>;
}
