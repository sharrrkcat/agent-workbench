import {
  ArrowLeft,
  BookOpen,
  Bot,
  ChevronRight,
  Database,
  Plug,
  Server,
  Settings2,
  SlidersHorizontal,
  Wrench,
  Boxes,
  LayoutDashboard,
  Plus,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { cn } from '@/lib/utils';
import { useModelsStore } from '../store/useModelsStore';
import { useTranslation } from 'react-i18next';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuAction,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar';
import {
  settingsGroups,
  settingsPageLabel,
  settingsRouteUrl,
  type SettingsNavigate,
  type SettingsRoute,
} from './settings/navigation';

function pageIcon(route: SettingsRoute) {
  if (route.section === 'models') {
    if (route.view === 'dashboard') return LayoutDashboard;
    if (route.view === 'providers') return Plug;
    if (route.view === 'localRuntime') return Server;
    return Boxes;
  }
  if (route.section === 'knowledge' || route.section === 'worldbook')
    return route.view === 'settings'
      ? SlidersHorizontal
      : route.section === 'knowledge'
        ? Database
        : BookOpen;
  if (route.section === 'personas') return Bot;
  return { general: Settings2, tools: Wrench }[route.section];
}

export function SettingsSidebar({
  route,
  onNavigate,
  returnTo = '/',
  onAddModel,
  modelsExpansion,
}: {
  route: SettingsRoute;
  onNavigate: SettingsNavigate;
  returnTo?: string;
  onAddModel: (trigger: HTMLElement | null) => void;
  modelsExpansion: number;
}) {
  const { t } = useTranslation('settings');
  const { setOpenMobile, isMobile } = useSidebar();
  const profiles = useModelsStore((state) => state.profiles);
  const loading = useModelsStore((state) => state.loading);
  const [modelsOpen, setModelsOpen] = useState(false);
  useEffect(() => { if (modelsExpansion) setModelsOpen(true); }, [modelsExpansion]);
  async function navigate(url: string) {
    if (await onNavigate(url)) setOpenMobile(false);
  }
  function pageItem(page: SettingsRoute) {
    const url = settingsRouteUrl(page);
    const active = url === settingsRouteUrl(route);
    const Icon = pageIcon(page);
    return (
      <SidebarMenuItem key={url}>
        <SidebarMenuButton
          type="button"
          data-settings-page={url}
          isActive={active}
          aria-current={active ? 'page' : undefined}
          onClick={() => void navigate(url)}
        >
          <Icon data-icon="inline-start" />
          <span>{t(settingsPageLabel(page))}</span>
        </SidebarMenuButton>
      </SidebarMenuItem>
    );
  }
  return (
    <Sidebar className="settings-sidebar" title={t('title')} aria-label={t('title')}>
      <SidebarHeader className="sidebar-header shrink-0 gap-4 p-3">
        <div className="sidebar-brand">{t('title')}</div>
      </SidebarHeader>
      <SidebarContent className="overscroll-contain overflow-x-hidden">
        <nav aria-label={t('title')} className="flex flex-col gap-2 pb-3">
          {settingsGroups.map((group) => (
            <SidebarGroup key={group.id} role="group" aria-label={t('sidebarGroups.' + group.id)}>
              <SidebarGroupLabel>{t('sidebarGroups.' + group.id)}</SidebarGroupLabel>
              <SidebarGroupContent className="flex flex-col gap-2">
                {group.menus.map((menu) => {
                  const Icon = pageIcon(menu.pages[0]);
                  return (
                    <SidebarMenu
                      key={menu.id}
                      className="settings-domain-menu"
                      aria-label={menu.section === 'personas' ? `${t(menu.label)} / ${t('sidebarGroups.' + group.id)}` : t(menu.label)}
                    >
                      {menu.pages.length === 1 ? (
                        pageItem(menu.pages[0])
                      ) : (
                        <SidebarMenuItem>
                          <Collapsible defaultOpen={false}
                            {...(menu.id === 'models' ? { open: modelsOpen, onOpenChange: setModelsOpen } : {})}>
                            <div className="group/settings-menu-heading relative">
                            <CollapsibleTrigger
                              render={
                                <SidebarMenuButton
                                  type="button"
                                  data-settings-menu={menu.id}
                                  className={menu.id === 'models'
                                    ? 'group-has-data-[sidebar=menu-action]/menu-item:pr-14 pointer-coarse:group-has-data-[sidebar=menu-action]/menu-item:pr-22' : undefined}
                                />
                              }
                            >
                              <Icon data-icon="inline-start" />
                              <span className="truncate">{t(menu.label)}</span>
                              <ChevronRight
                                data-icon="inline-end"
                                className={cn('ml-auto transition-transform group-aria-expanded/menu-button:rotate-90',
                                  menu.id === 'models' && 'absolute right-2 pointer-coarse:right-3.5')}
                              />
                            </CollapsibleTrigger>
                            {menu.id === 'models' ? <SidebarMenuAction type="button"
                              aria-label={t('llm:addAnyModel')} title={t('llm:addAnyModel')} disabled={loading}
                              className="right-7 opacity-0 group-hover/settings-menu-heading:opacity-100 group-has-[:focus-visible]/settings-menu-heading:opacity-100 pointer-coarse:right-11 pointer-coarse:opacity-100"
                              onClick={(event) => {
                                const trigger = isMobile ? null : event.currentTarget;
                                setOpenMobile(false);
                                onAddModel(trigger);
                              }}><Plus /></SidebarMenuAction> : null}
                            </div>
                            <CollapsibleContent keepMounted>
                              <SidebarMenu className="ml-3.5 w-auto gap-1 border-l border-sidebar-border pl-2.5">
                                {menu.pages.filter((page) => menu.id !== 'models' || page.section !== 'models'
                                  || page.view === 'dashboard' || profiles.some((profile) => profile.kind === page.view)).map(pageItem)}
                              </SidebarMenu>
                            </CollapsibleContent>
                          </Collapsible>
                        </SidebarMenuItem>
                      )}
                    </SidebarMenu>
                  );
                })}
              </SidebarGroupContent>
            </SidebarGroup>
          ))}
        </nav>
      </SidebarContent>
      <SidebarFooter className="shrink-0 p-3">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton type="button" onClick={() => void navigate(returnTo)}>
              <ArrowLeft data-icon="inline-start" />
              <span>{t('backToChat')}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
