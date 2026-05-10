import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import enCommon from './resources/en/common.json';
import enSettings from './resources/en/settings.json';
import enChat from './resources/en/chat.json';
import enErrors from './resources/en/errors.json';
import zhCommon from './resources/zh-CN/common.json';
import zhSettings from './resources/zh-CN/settings.json';
import zhChat from './resources/zh-CN/chat.json';
import zhErrors from './resources/zh-CN/errors.json';

export const LOCALE_STORAGE_KEY = 'agent-workbench.locale';
export const SUPPORTED_LOCALES = ['en', 'zh-CN'] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

function storedLocale(): SupportedLocale {
  if (typeof window === 'undefined') return 'en';
  const value = window.localStorage.getItem(LOCALE_STORAGE_KEY);
  return SUPPORTED_LOCALES.includes(value as SupportedLocale) ? (value as SupportedLocale) : 'en';
}

void i18n.use(initReactI18next).init({
  resources: {
    en: {
      common: enCommon,
      settings: enSettings,
      chat: enChat,
      errors: enErrors,
    },
    'zh-CN': {
      common: zhCommon,
      settings: zhSettings,
      chat: zhChat,
      errors: zhErrors,
    },
  },
  lng: storedLocale(),
  fallbackLng: 'en',
  defaultNS: 'common',
  ns: ['common', 'settings', 'chat', 'errors'],
  interpolation: {
    escapeValue: false,
  },
  returnNull: false,
});

i18n.on('languageChanged', (language) => {
  if (typeof window === 'undefined') return;
  const locale = SUPPORTED_LOCALES.includes(language as SupportedLocale) ? language : 'en';
  window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
});

export function changeLocale(locale: SupportedLocale) {
  return i18n.changeLanguage(locale);
}

export default i18n;
