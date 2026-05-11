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
import enAgents from './resources/en/agents.json';
import enCapabilities from './resources/en/capabilities.json';
import enPet from './resources/en/pet.json';
import enRenderers from './resources/en/renderers.json';
import enComfyui from './resources/en/comfyui.json';
import zhCommon from './resources/zh-CN/common.json';
import zhSettings from './resources/zh-CN/settings.json';
import zhChat from './resources/zh-CN/chat.json';
import zhErrors from './resources/zh-CN/errors.json';
import zhStatus from './resources/zh-CN/status.json';
import zhRuns from './resources/zh-CN/runs.json';
import zhLlm from './resources/zh-CN/llm.json';
import zhKnowledge from './resources/zh-CN/knowledge.json';
import zhWorldbook from './resources/zh-CN/worldbook.json';
import zhAgents from './resources/zh-CN/agents.json';
import zhCapabilities from './resources/zh-CN/capabilities.json';
import zhPet from './resources/zh-CN/pet.json';
import zhRenderers from './resources/zh-CN/renderers.json';
import zhComfyui from './resources/zh-CN/comfyui.json';

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
      status: enStatus,
      runs: enRuns,
      llm: enLlm,
      knowledge: enKnowledge,
      worldbook: enWorldbook,
      agents: enAgents,
      capabilities: enCapabilities,
      pet: enPet,
      renderers: enRenderers,
      comfyui: enComfyui,
    },
    'zh-CN': {
      common: zhCommon,
      settings: zhSettings,
      chat: zhChat,
      errors: zhErrors,
      status: zhStatus,
      runs: zhRuns,
      llm: zhLlm,
      knowledge: zhKnowledge,
      worldbook: zhWorldbook,
      agents: zhAgents,
      capabilities: zhCapabilities,
      pet: zhPet,
      renderers: zhRenderers,
      comfyui: zhComfyui,
    },
  },
  lng: storedLocale(),
  fallbackLng: 'en',
  defaultNS: 'common',
  ns: ['common', 'settings', 'chat', 'errors', 'status', 'runs', 'llm', 'knowledge', 'worldbook', 'agents', 'capabilities', 'pet', 'renderers', 'comfyui'],
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
