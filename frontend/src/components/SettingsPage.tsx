import { ArrowLeft, Bot, Boxes, Settings } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { ErrorBanner } from './ErrorBanner';
import { SettingsConsole } from './settings/SettingsConsole';
import type { SettingsSection } from './settings/SettingsNav';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { changeLocale, type SupportedLocale } from '../i18n';

export function SettingsPage({ initialSection = 'general', onBack }: { initialSection?: SettingsSection; onBack: () => void }) {
  const { agentConfigs, capabilityConfigs } = useWorkbenchStore();
  const { t } = useTranslation(['settings', 'common']);

  return (
    <main className="settings-page">
      <header className="settings-page-header">
        <button className="back-button" type="button" onClick={onBack}>
          <ArrowLeft size={17} />
          {t('common:backToChat')}
        </button>
        <div className="settings-heading">
          <div className="settings-heading-icon">
            <Settings size={20} />
          </div>
          <div>
            <h1>{t('settings:title')}</h1>
            <p>{t('settings:description')}</p>
          </div>
        </div>
        <div className="settings-page-stats" aria-label="Settings summary">
          <LanguageSelect />
          <span>
            <Bot size={14} />
            {t('settings:summary.agents', { count: agentConfigs.length })}
          </span>
          <span>
            <Boxes size={14} />
            {t('settings:summary.capabilities', { count: capabilityConfigs.length })}
          </span>
        </div>
      </header>
      <ErrorBanner />
      <SettingsConsole initialSection={initialSection} />
    </main>
  );
}

function LanguageSelect() {
  const { i18n, t } = useTranslation('common');
  const currentLocale = i18n.resolvedLanguage === 'zh-CN' ? 'zh-CN' : 'en';

  return (
    <label className="language-select">
      <span className="sr-only">{t('language')}</span>
      <select value={currentLocale} onChange={(event) => void changeLocale(event.currentTarget.value as SupportedLocale)}>
        <option value="en">{t('languageEnglish')}</option>
        <option value="zh-CN">{t('languageChinese')}</option>
      </select>
    </label>
  );
}
