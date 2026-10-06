import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { SidebarInset, SidebarTrigger } from '@/components/ui/sidebar';
import { SettingsSidebar } from './SettingsSidebar';
import { GeneralPanel } from './settings/GeneralPanel';
import { KnowledgePanel } from './settings/KnowledgePanel';
import { ModelsPanel } from './settings/ModelsPanel';
import { PersonasPanel } from './settings/PersonasPanel';
import { ToolsPanel } from './settings/ToolsPanel';
import { WorldbookPanel } from './settings/WorldbookPanel';
import { readSettingsRoute, settingsMenuLabel, settingsPageLabel, settingsRouteUrl, type SettingsNavigate } from './settings/navigation';
import { SettingsLeaveContext, type LeaveGuard } from './settings/resources/ResourceUI';
import { ModelCreationDialog } from './settings/models/ModelCreationDialog';
import { modelKinds, type ModelKind } from '../types/models';

export function SettingsPage({
  search,
  onNavigate,
  onLeaveGuardChange,
  returnTo,
}: {
  search: string;
  onNavigate: SettingsNavigate;
  onLeaveGuardChange: (guard: LeaveGuard) => void;
  returnTo?: string;
}) {
  const { t } = useTranslation('settings');
  const route = readSettingsRoute(search);
  const scroller = useRef<HTMLDivElement>(null);
  const sidebarTrigger = useRef<HTMLButtonElement>(null);
  const [creating, setCreating] = useState<{ kind: ModelKind; trigger: HTMLElement | null } | null>(null);
  const creationBusy = useRef(false);
  const [modelListKind, setModelListKind] = useState<ModelKind | null>(null);
  const [modelsExpansion, setModelsExpansion] = useState(0);
  const guard = useRef<LeaveGuard>(async () => true);
  const register = useCallback((value: LeaveGuard) => {
    guard.current = value;
    return () => {
      if (guard.current === value) guard.current = async () => true;
    };
  }, []);
  useEffect(() => {
    onLeaveGuardChange(async (target) => {
      if (creationBusy.current || !(await guard.current(target))) return false;
      setCreating(null);
      return true;
    });
    return () => onLeaveGuardChange(async () => true);
  }, [onLeaveGuardChange]);
  useEffect(() => {
    scroller.current?.scrollTo(0, 0);
    setModelListKind((kind) => route.section === 'models' && route.view === kind ? kind : null);
  }, [route.section, route.view]);
  return (
    <SettingsLeaveContext.Provider value={register}>
      <SettingsSidebar route={route} onNavigate={async (url) => {
        if (!(await onNavigate(url))) return false;
        setModelListKind(null);
        return true;
      }} returnTo={returnTo} modelsExpansion={modelsExpansion}
        onAddModel={(trigger) => setCreating({
          kind: route.section === 'models' ? modelKinds.find((kind) => kind === route.view) ?? 'llm' : 'llm',
          trigger,
        })} />
      <SidebarInset className="settings-page min-h-0 min-w-0 overflow-hidden">
        <header className="settings-header">
          <SidebarTrigger ref={sidebarTrigger} />
          <div className="settings-heading">
            <h1>
              {t(settingsMenuLabel(route))}
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
            {route.section === 'models' ? <ModelsPanel view={route.view} onNavigate={onNavigate}
              listOnlyKind={modelListKind} onOpenEditor={() => setModelListKind(null)} /> : null}
            {route.section === 'personas' ? <PersonasPanel key={route.view} collection={route.view} /> : null}
            {route.section === 'knowledge' ? <KnowledgePanel view={route.view} /> : null}
            {route.section === 'worldbook' ? <WorldbookPanel view={route.view} /> : null}
            {route.section === 'tools' ? <ToolsPanel /> : null}
          </div>
        </div>
      </SidebarInset>
      {creating ? <ModelCreationDialog kind={creating.kind} onClose={() => setCreating(null)}
        returnFocus={() => creating.trigger?.isConnected ? creating.trigger : sidebarTrigger.current}
        onBusyChange={(busy) => { creationBusy.current = busy; }}
        onCreated={async (profile) => {
          setCreating(null);
          setModelListKind(profile.kind);
          if (await onNavigate(settingsRouteUrl({ section: 'models', view: profile.kind })))
            setModelsExpansion((value) => value + 1);
          else setModelListKind(null);
        }} /> : null}
    </SettingsLeaveContext.Provider>
  );
}
