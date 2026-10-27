import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import { farkle as enFarkle, language as enLanguage, back as enBack, close as enClose,
  pagination as enPagination } from '../i18n/resources/en/common.json';
import { farkle as zhFarkle, language as zhLanguage, back as zhBack, close as zhClose,
  pagination as zhPagination } from '../i18n/resources/zh-CN/common.json';
import { toggleSidebar as enToggleSidebar } from '../i18n/resources/en/personas.json';
import { toggleSidebar as zhToggleSidebar } from '../i18n/resources/zh-CN/personas.json';

const key = 'farkle.locale';
const stored = window.localStorage.getItem(key);
const languages = navigator.languages?.length ? navigator.languages : [navigator.language];
const detected = languages.map((language) => language.toLowerCase().split('-')[0])
  .find((language) => language === 'zh' || language === 'en');
const locale = stored === 'en' || stored === 'zh-CN' ? stored : detected === 'zh' ? 'zh-CN' : 'en';
if (stored !== locale) window.localStorage.setItem(key, locale);
void i18n.use(initReactI18next).init({
  resources: {
    en: { common: { farkle: enFarkle, language: enLanguage, back: enBack, close: enClose,
      pagination: enPagination, playground: { farkle: 'Farkle' } }, personas: { toggleSidebar: enToggleSidebar } },
    'zh-CN': { common: { farkle: zhFarkle, language: zhLanguage, back: zhBack, close: zhClose,
      pagination: zhPagination, playground: { farkle: 'Farkle' } }, personas: { toggleSidebar: zhToggleSidebar } },
  },
  lng: locale, fallbackLng: 'en', defaultNS: 'common',
  ns: ['common', 'personas'], interpolation: { escapeValue: false }, returnNull: false,
});
document.documentElement.lang = i18n.language;
i18n.on('languageChanged', (language) => {
  document.documentElement.lang = language;
  window.localStorage.setItem(key, language);
});
