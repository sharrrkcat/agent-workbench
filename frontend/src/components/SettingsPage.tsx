import { useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { SidebarInset, SidebarTrigger } from '@/components/ui/sidebar';
import { SettingsSidebar } from './SettingsSidebar';
import { GeneralPanel } from './settings/GeneralPanel';
import { KnowledgePanel } from './settings/KnowledgePanel';
import { ModelsPanel } from './settings/ModelsPanel';
import { PersonasPanel } from './settings/PersonasPanel';
import { ToolsPanel } from './settings/ToolsPanel';
import { WorldbookPanel } from './settings/WorldbookPanel';
import { readSettingsRoute, settingsPageLabel, type SettingsNavigate } from './settings/navigation';
import { SettingsLeaveContext, type LeaveGuard } from './settings/resources/ResourceUI';

export function SettingsPage({
  search,
  onNavigate,
  onLeaveGuardChange,
}: {
  search: string;
  onNavigate: SettingsNavigate;
  onLeaveGuardChange: (guard: LeaveGuard) => void;
}) {
  const { t } = useTranslation('settings');
  const route = readSettingsRoute(search);
  const scroller = useRef<HTMLDivElement>(null);
  const guard = useRef<LeaveGuard>(async () => true);
  const register = useCallback((value: LeaveGuard) => {
    guard.current = value;
    return () => {
      if (guard.current === value) guard.current = async () => true;
    };
  }, []);
  useEffect(() => {
    onLeaveGuardChange((target) => guard.current(target));
    return () => onLeaveGuardChange(async () => true);
  }, [onLeaveGuardChange]);
  useEffect(() => {
    scroller.current?.scrollTo(0, 0);
  }, [route.section, route.view]);
  return (
    <SettingsLeaveContext.Provider value={register}>
      <SettingsSidebar route={route} onNavigate={onNavigate} />
      <SidebarInset className="settings-page min-h-0 min-w-0 overflow-hidden">
        <header className="settings-header">
          <SidebarTrigger />
          <div className="settings-heading">
            <h1>
              {t(route.section)}
              {route.view ? (
                <>
                  {' '}
                  <span aria-hidden="true">/</span> {t(settingsPageLabel(route))}
                </>
              ) : null}
            </h1>
          </div>
        </header>
        <div ref={scroller} className="settings-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain">
          <div className="settings-content">
            {route.section === 'general' ? <GeneralPanel /> : null}
            {route.section === 'models' ? <ModelsPanel view={route.view} onNavigate={onNavigate} /> : null}
            {route.section === 'personas' ? <PersonasPanel /> : null}
            {route.section === 'knowledge' ? <KnowledgePanel view={route.view} /> : null}
            {route.section === 'worldbook' ? <WorldbookPanel view={route.view} /> : null}
            {route.section === 'tools' ? <ToolsPanel /> : null}
          </div>
        </div>
      </SidebarInset>
    </SettingsLeaveContext.Provider>
  );
}
