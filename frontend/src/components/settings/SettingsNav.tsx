import { Activity, Bot, BookOpenText, Boxes, BrainCircuit, Code2, Database, Info, Palette, Settings, SlidersHorizontal } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export type SettingsSection = 'general' | 'appearance' | 'llm' | 'knowledge' | 'worldbook' | 'agents' | 'capabilities' | 'data' | 'diagnostics' | 'developer' | 'about';
export type LlmSettingsSubsection = 'defaults' | 'providers' | 'models';
export type KnowledgeSettingsSubsection = 'defaults' | 'embedding_models' | 'knowledge_bases';
export type WorldbookSettingsSubsection = 'defaults' | 'worldbooks';
export type SettingsInitialTarget = {
  section: SettingsSection;
  knowledgeSubsection?: KnowledgeSettingsSubsection;
  worldbookSubsection?: WorldbookSettingsSubsection;
};

const sections: { id: SettingsSection; labelKey: string; icon: typeof Settings }[] = [
  { id: 'general', labelKey: 'sections.general', icon: Settings },
  { id: 'appearance', labelKey: 'sections.appearance', icon: Palette },
  { id: 'llm', labelKey: 'sections.llm', icon: SlidersHorizontal },
  { id: 'knowledge', labelKey: 'sections.knowledge', icon: BrainCircuit },
  { id: 'worldbook', labelKey: 'sections.worldbook', icon: BookOpenText },
  { id: 'agents', labelKey: 'sections.agents', icon: Bot },
  { id: 'capabilities', labelKey: 'sections.capabilities', icon: Boxes },
  { id: 'data', labelKey: 'sections.data', icon: Database },
  { id: 'diagnostics', labelKey: 'sections.diagnostics', icon: Activity },
  { id: 'developer', labelKey: 'sections.developer', icon: Code2 },
  { id: 'about', labelKey: 'sections.about', icon: Info },
];

export function SettingsNav({
  activeSection,
  activeLlmSubsection = 'defaults',
  activeKnowledgeSubsection = 'defaults',
  activeWorldbookSubsection = 'defaults',
  onChange,
  onLlmSubsectionChange,
  onKnowledgeSubsectionChange,
  onWorldbookSubsectionChange,
}: {
  activeSection: SettingsSection;
  onChange: (section: SettingsSection) => void;
  activeLlmSubsection?: LlmSettingsSubsection;
  activeKnowledgeSubsection?: KnowledgeSettingsSubsection;
  activeWorldbookSubsection?: WorldbookSettingsSubsection;
  onLlmSubsectionChange?: (subsection: LlmSettingsSubsection) => void;
  onKnowledgeSubsectionChange?: (subsection: KnowledgeSettingsSubsection) => void;
  onWorldbookSubsectionChange?: (subsection: WorldbookSettingsSubsection) => void;
}) {
  const { t } = useTranslation('settings');

  return (
    <nav className="settings-nav" aria-label="Settings sections">
      {sections.map((section) => {
        const Icon = section.icon;
        return (
          <div key={section.id} className="settings-nav-group">
            <button
              type="button"
              className={activeSection === section.id ? 'active' : ''}
              onClick={() => onChange(section.id)}
            >
              <Icon size={16} />
              <span>{t(section.labelKey)}</span>
            </button>
            {section.id === 'llm' && activeSection === 'llm' ? (
              <div className="settings-subnav" aria-label="LLM settings sections">
                <button
                  type="button"
                  className={activeLlmSubsection === 'defaults' ? 'active' : ''}
                  onClick={() => onLlmSubsectionChange?.('defaults')}
                >
                  <span>{t('subsections.defaults')}</span>
                </button>
                <button
                  type="button"
                  className={activeLlmSubsection === 'providers' ? 'active' : ''}
                  onClick={() => onLlmSubsectionChange?.('providers')}
                >
                  <span>{t('subsections.providerProfiles')}</span>
                </button>
                <button
                  type="button"
                  className={activeLlmSubsection === 'models' ? 'active' : ''}
                  onClick={() => onLlmSubsectionChange?.('models')}
                >
                  <span>{t('subsections.modelProfiles')}</span>
                </button>
              </div>
            ) : null}
            {section.id === 'knowledge' && activeSection === 'knowledge' ? (
              <div className="settings-subnav" aria-label="Knowledge settings sections">
                <button
                  type="button"
                  className={activeKnowledgeSubsection === 'defaults' ? 'active' : ''}
                  onClick={() => onKnowledgeSubsectionChange?.('defaults')}
                >
                  <span>{t('subsections.defaults')}</span>
                </button>
                <button
                  type="button"
                  className={activeKnowledgeSubsection === 'embedding_models' ? 'active' : ''}
                  onClick={() => onKnowledgeSubsectionChange?.('embedding_models')}
                >
                  <span>{t('subsections.embeddingModels')}</span>
                </button>
                <button
                  type="button"
                  className={activeKnowledgeSubsection === 'knowledge_bases' ? 'active' : ''}
                  onClick={() => onKnowledgeSubsectionChange?.('knowledge_bases')}
                >
                  <span>{t('subsections.knowledgeBases')}</span>
                </button>
              </div>
            ) : null}
            {section.id === 'worldbook' && activeSection === 'worldbook' ? (
              <div className="settings-subnav" aria-label={t('aria.worldbookSettingsSections')}>
                <button
                  type="button"
                  className={activeWorldbookSubsection === 'defaults' ? 'active' : ''}
                  onClick={() => onWorldbookSubsectionChange?.('defaults')}
                >
                  <span>{t('subsections.defaults')}</span>
                </button>
                <button
                  type="button"
                  className={activeWorldbookSubsection === 'worldbooks' ? 'active' : ''}
                  onClick={() => onWorldbookSubsectionChange?.('worldbooks')}
                >
                  <span>{t('subsections.worldbooks')}</span>
                </button>
              </div>
            ) : null}
          </div>
        );
      })}
    </nav>
  );
}
