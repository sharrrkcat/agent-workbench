import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Boxes, Compass, MessageSquarePlus, MoreHorizontal, Settings2, Trash2 } from 'lucide-react';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { cn } from '@/lib/utils';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useCogitaStore } from '../store/useCogitaStore';
import { NewProjectDialog } from './projects/NewProjectDialog';
import { ProjectsTree } from './projects/ProjectsTree';
import { projectUrl } from './projects/navigation';
import type { ProjectKind } from '../types/projects';
import type { SettingsNavigate } from './settings/navigation';

export function SessionSidebar({ onOpenSettings, onNavigate, onSelectSession, onCreateSession, onSessionDeleted, onProjectDeleted }: {
  onOpenSettings: () => Promise<boolean>; onNavigate: SettingsNavigate;
  onSelectSession: (id: string, projectId: string | null) => Promise<boolean>;
  onCreateSession: (projectId?: string | null) => Promise<boolean>;
  onSessionDeleted: (id: string) => void; onProjectDeleted: (id: string) => void;
}) {
  const { confirm, confirmation } = useConfirmDialog();
  const { t } = useTranslation('personas');
  const { setOpenMobile } = useSidebar();
  const allSessions = useCogitaStore((state) => state.sessions);
  const sessions = allSessions.filter((session) => session.kind === 'ordinary');
  const current = useCogitaStore((state) => state.currentSession);
  const remove = useCogitaStore((state) => state.deleteSession);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [creating, setCreating] = useState<ProjectKind | null>(null);

  async function deleteSession(id: string) {
    if (!(await confirm(t('deleteSessionConfirm'), { destructive: true }))) return;
    setDeleting(id);
    try {
      await remove(id);
      if (!useCogitaStore.getState().sessions.some((session) => session.session_id === id)) onSessionDeleted(id);
    } finally {
      setDeleting(null);
    }
  }

  return (
    <>
      <Sidebar className="session-sidebar" aria-label={t('sessions')}>
        <SidebarHeader className="sidebar-header shrink-0 gap-4 p-3">
          <div className="sidebar-brand">{t('common:appName')}</div>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                type="button"
                onClick={async () => {
                  if (await onCreateSession()) setOpenMobile(false);
                }}
              >
                <MessageSquarePlus data-icon="inline-start" />
                <span>{t('newSession')}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton type="button" onClick={() => { setCreating('workspace'); setOpenMobile(false); }}>
                <Compass data-icon="inline-start" />
                <span>{t('newWorkspace')}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton type="button" onClick={() => { setCreating('timeline'); setOpenMobile(false); }}>
                <Boxes data-icon="inline-start" />
                <span>{t('newTimeline')}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>
        <SidebarContent className="session-list overflow-x-hidden overscroll-contain">
          <ProjectsTree onNavigate={onNavigate} onSelectSession={onSelectSession} onCreateSession={onCreateSession}
            onSessionDeleted={onSessionDeleted} onProjectDeleted={onProjectDeleted} />
          <SidebarGroup>
            <SidebarGroupLabel>{t('sessions')}</SidebarGroupLabel>
            <SidebarMenu>
              {sessions.map((session) => {
                const title = session.title.trim() || t('newSession');
                const selected = session.session_id === current?.session_id;
                return (
                  <SidebarMenuItem
                    key={session.session_id}
                    className={cn('session-item', selected && 'selected')}
                  >
                    <SidebarMenuButton
                      type="button"
                      className="session-select"
                      title={title}
                      isActive={selected}
                      aria-current={selected ? 'page' : undefined}
                      disabled={deleting === session.session_id}
                      onClick={async () => {
                        if (await onSelectSession(session.session_id, null)) setOpenMobile(false);
                      }}
                    >
                      <span>{title}</span>
                    </SidebarMenuButton>
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        render={
                          <SidebarMenuAction
                            type="button"
                            className="session-menu"
                            showOnHover
                            aria-label={t('sessionActions', { title })}
                          />
                        }
                      >
                        <MoreHorizontal />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-40">
                        <DropdownMenuGroup>
                          <DropdownMenuItem
                            variant="destructive"
                            disabled={deleting !== null}
                            onClick={() => void deleteSession(session.session_id)}
                          >
                            <Trash2 data-icon="inline-start" />
                            {t('deleteSession')}
                          </DropdownMenuItem>
                        </DropdownMenuGroup>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter className="sidebar-footer shrink-0 p-3">
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                type="button"
                className="sidebar-settings-button"
                onClick={async () => {
                  if (await onOpenSettings()) setOpenMobile(false);
                }}
              >
                <Settings2 data-icon="inline-start" />
                <span>{t('settings')}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
        {confirmation}
      </Sidebar>
      {creating ? <NewProjectDialog kind={creating} onClose={() => setCreating(null)} onNavigate={onNavigate}
        onSaved={(project) => { setCreating(null); void onNavigate(projectUrl(project.id)); }} /> : null}
    </>
  );
}
