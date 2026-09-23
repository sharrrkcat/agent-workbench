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
  Network,
} from 'lucide-react';
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
  if (route.section === 'models')
    return { profiles: Boxes, providers: Plug, localRuntime: Server, service: Network }[route.view];
  if (route.section === 'knowledge' || route.section === 'worldbook')
    return route.view === 'settings'
      ? SlidersHorizontal
      : route.section === 'knowledge'
        ? Database
        : BookOpen;
  return { general: Settings2, personas: Bot, tools: Wrench }[route.section];
}

export function SettingsSidebar({
  route,
  onNavigate,
}: {
  route: SettingsRoute;
  onNavigate: SettingsNavigate;
}) {
  const { t } = useTranslation('settings');
  const { setOpenMobile } = useSidebar();
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
                      key={menu.section}
                      className="settings-domain-menu"
                      aria-label={t(menu.section)}
                    >
                      {menu.pages.length === 1 ? (
                        pageItem(menu.pages[0])
                      ) : (
                        <SidebarMenuItem>
                          <Collapsible defaultOpen={false}>
                            <CollapsibleTrigger
                              render={
                                <SidebarMenuButton
                                  type="button"
                                  data-settings-menu={menu.section}
                                />
                              }
                            >
                              <Icon data-icon="inline-start" />
                              <span>{t(menu.section)}</span>
                              <ChevronRight
                                data-icon="inline-end"
                                className="ml-auto transition-transform group-aria-expanded/menu-button:rotate-90"
                              />
                            </CollapsibleTrigger>
                            <CollapsibleContent keepMounted>
                              <SidebarMenu className="ml-3.5 w-auto gap-1 border-l border-sidebar-border pl-2.5">
                                {menu.pages.map(pageItem)}
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
            <SidebarMenuButton type="button" onClick={() => void navigate('/')}>
              <ArrowLeft data-icon="inline-start" />
              <span>{t('backToChat')}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
