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

export function SessionSidebar({ onOpenSettings }: { onOpenSettings: () => void }) {
  const { confirm, confirmation } = useConfirmDialog();
  const { t } = useTranslation('personas');
  const { setOpenMobile } = useSidebar();
  const sessions = useCogitaStore((state) => state.sessions);
  const current = useCogitaStore((state) => state.currentSession);
  const select = useCogitaStore((state) => state.selectSession);
  const create = useCogitaStore((state) => state.createSession);
  const remove = useCogitaStore((state) => state.deleteSession);
  const [deleting, setDeleting] = useState<string | null>(null);

  async function deleteSession(id: string) {
    if (!(await confirm(t('deleteSessionConfirm'), { destructive: true }))) return;
    setDeleting(id);
    try {
      await remove(id);
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
                onClick={() => {
                  void create();
                  setOpenMobile(false);
                }}
              >
                <MessageSquarePlus data-icon="inline-start" />
                <span>{t('newSession')}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton type="button" disabled>
                <Compass data-icon="inline-start" />
                <span>{t('featureOne')}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
            <SidebarMenuItem>
              <SidebarMenuButton type="button" disabled>
                <Boxes data-icon="inline-start" />
                <span>{t('featureTwo')}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>
        <SidebarGroupLabel className="shrink-0 px-5">{t('sessions')}</SidebarGroupLabel>
        <SidebarContent className="session-list overflow-x-hidden overscroll-contain">
          <SidebarGroup>
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
                      onClick={() => {
                        void select(session.session_id);
                        setOpenMobile(false);
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
                onClick={() => {
                  onOpenSettings();
                  setOpenMobile(false);
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
    </>
  );
}
