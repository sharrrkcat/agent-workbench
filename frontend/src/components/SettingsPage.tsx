import { ArrowLeft } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { GeneralPanel } from './settings/GeneralPanel';
import { KnowledgePanel } from './settings/KnowledgePanel';
import { ModelsPanel } from './settings/ModelsPanel';
import { PersonasPanel } from './settings/PersonasPanel';
import { ToolsPanel } from './settings/ToolsPanel';
import { WorldbookPanel } from './settings/WorldbookPanel';
import { readSettingsSection, settingsSections, settingsSectionUrl } from './settings/navigation';
import { useSettingsFeedback } from './settings/useSettingsFeedback';
import { SettingsLeaveContext } from './settings/resources/ResourceUI';

export function SettingsPage({ onBack, onLeaveGuardChange }: { onBack: () => void; onLeaveGuardChange?: (guard: () => boolean) => void }) {
  const { t } = useTranslation('settings');
  const [section, setSection] = useState(() => readSettingsSection(window.location.search));
  const { message, error, run } = useSettingsFeedback();
  const guard = useRef<() => boolean>(() => true);
  const register = useCallback((value: () => boolean) => {
    guard.current = value;
    return () => { if (guard.current === value) guard.current = () => true; };
  }, []);
  useEffect(() => {
    onLeaveGuardChange?.(() => guard.current());
    return () => onLeaveGuardChange?.(() => true);
  }, [onLeaveGuardChange, section]);
  return (
    <SettingsLeaveContext.Provider value={register}>
    <div className="settings-page">
      <header className="settings-header">
        <button className="icon-button" type="button" onClick={() => { if (guard.current()) onBack(); }} title={t('common:back')}>
          <ArrowLeft size={18} />
        </button>
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
            <button
              key={item}
              type="button"
              className={section === item ? 'active' : ''}
              onClick={() => {
                if (section === item || !guard.current()) return;
                setSection(item);
                window.history.replaceState({}, '', settingsSectionUrl(item));
              }}
            >
              {t(item)}
            </button>
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
