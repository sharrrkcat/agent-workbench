import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { ArrowLeft } from 'lucide-react';
import { useCallback, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { GeneralPanel } from './settings/GeneralPanel';
import { KnowledgePanel } from './settings/KnowledgePanel';
import { ModelsPanel } from './settings/ModelsPanel';
import { PersonasPanel } from './settings/PersonasPanel';
import { ToolsPanel } from './settings/ToolsPanel';
import { WorldbookPanel } from './settings/WorldbookPanel';
import { readSettingsSection, settingsSections, settingsSectionUrl } from './settings/navigation';
import { useSettingsFeedback } from './settings/useSettingsFeedback';
import { SettingsLeaveContext, type LeaveGuard } from './settings/resources/ResourceUI';

export function SettingsPage({
  search,
  onNavigate,
  onBack,
  onLeaveGuardChange,
}: {
  search: string;
  onNavigate: (url: string, replace?: boolean) => Promise<void>;
  onBack: () => void;
  onLeaveGuardChange?: (guard: LeaveGuard) => void;
}) {
  const { t } = useTranslation('settings');
  const section = readSettingsSection(search);
  const { message, error, run } = useSettingsFeedback();
  const guard = useRef<LeaveGuard>(async () => true);
  const register = useCallback((value: LeaveGuard) => {
    guard.current = value;
    return () => {
      if (guard.current === value) guard.current = async () => true;
    };
  }, []);
  useEffect(() => {
    onLeaveGuardChange?.(() => guard.current());
    return () => onLeaveGuardChange?.(async () => true);
  }, [onLeaveGuardChange, section]);
  return (
    <SettingsLeaveContext.Provider value={register}>
      <div className="settings-page">
        <header className="settings-header">
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  type="button"
                  onClick={onBack}
                  variant="ghost"
                  size="icon"
                  aria-label={t('common:back')}
                />
              }
            >
              <ArrowLeft size={18} />
            </TooltipTrigger>
            <TooltipContent>{t('common:back')}</TooltipContent>
          </Tooltip>
          <div>
            <h1>{t('title')}</h1>
          </div>
          <div className="settings-feedback" role="status">
            {message ? <span className="success-text">{message}</span> : null}
            {error ? <span className="error-text">{error}</span> : null}
          </div>
        </header>
        <div className="settings-layout">
          <nav className="settings-nav" aria-label={t('title')}>
            {settingsSections.map((item) => (
              <Button
                key={item}
                type="button"
                onClick={() => {
                  if (section !== item) void onNavigate(settingsSectionUrl(item), true);
                }}
                variant={section === item ? 'secondary' : 'ghost'}
                aria-current={section === item ? 'page' : undefined}
              >
                {t(item)}
              </Button>
            ))}
          </nav>
          <main className="settings-content">
            {section === 'general' ? <GeneralPanel save={run} /> : null}
            {section === 'models' ? <ModelsPanel /> : null}
            {section === 'personas' ? <PersonasPanel /> : null}
            {section === 'knowledge' ? <KnowledgePanel /> : null}
            {section === 'worldbook' ? <WorldbookPanel /> : null}
            {section === 'tools' ? <ToolsPanel /> : null}
          </main>
        </div>
      </div>
    </SettingsLeaveContext.Provider>
  );
}
