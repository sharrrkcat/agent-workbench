import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import enCommon from './resources/en/common.json';
import enSettings from './resources/en/settings.json';
import enChat from './resources/en/chat.json';
import enErrors from './resources/en/errors.json';
import enStatus from './resources/en/status.json';
import enRuns from './resources/en/runs.json';
import enLlm from './resources/en/llm.json';
import enKnowledge from './resources/en/knowledge.json';
import enWorldbook from './resources/en/worldbook.json';
import enPet from './resources/en/pet.json';
import enRenderers from './resources/en/renderers.json';
import zhCommon from './resources/zh-CN/common.json';
import zhSettings from './resources/zh-CN/settings.json';
import zhChat from './resources/zh-CN/chat.json';
import zhErrors from './resources/zh-CN/errors.json';
import zhStatus from './resources/zh-CN/status.json';
import zhRuns from './resources/zh-CN/runs.json';
import zhLlm from './resources/zh-CN/llm.json';
import zhKnowledge from './resources/zh-CN/knowledge.json';
import zhWorldbook from './resources/zh-CN/worldbook.json';
import zhPet from './resources/zh-CN/pet.json';
import zhRenderers from './resources/zh-CN/renderers.json';

export const LOCALE_STORAGE_KEY = 'agent-workbench.locale';
export const SUPPORTED_LOCALES = ['en', 'zh-CN'] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

const resources = {
  en: { common: enCommon, settings: enSettings, chat: enChat, errors: enErrors, status: enStatus, runs: enRuns, llm: enLlm, knowledge: enKnowledge, worldbook: enWorldbook, pet: enPet, renderers: enRenderers },
  'zh-CN': { common: zhCommon, settings: zhSettings, chat: zhChat, errors: zhErrors, status: zhStatus, runs: zhRuns, llm: zhLlm, knowledge: zhKnowledge, worldbook: zhWorldbook, pet: zhPet, renderers: zhRenderers },
};
const stored = typeof window === 'undefined' ? 'en' : window.localStorage.getItem(LOCALE_STORAGE_KEY);
void i18n.use(initReactI18next).init({ resources, lng: SUPPORTED_LOCALES.includes(stored as SupportedLocale) ? stored || 'en' : 'en', fallbackLng: 'en', defaultNS: 'common', ns: Object.keys(resources.en), interpolation: { escapeValue: false }, returnNull: false });
i18n.on('languageChanged', (language) => { if (typeof window !== 'undefined') window.localStorage.setItem(LOCALE_STORAGE_KEY, SUPPORTED_LOCALES.includes(language as SupportedLocale) ? language : 'en'); });
export function changeLocale(locale: SupportedLocale) { return i18n.changeLanguage(locale); }
export default i18n;
