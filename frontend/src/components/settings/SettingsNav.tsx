import { Activity, Bot, Boxes, BrainCircuit, Code2, Database, Info, Palette, Settings, SlidersHorizontal } from 'lucide-react';

export type SettingsSection = 'general' | 'appearance' | 'llm' | 'knowledge' | 'agents' | 'capabilities' | 'data' | 'diagnostics' | 'developer' | 'about';
export type LlmSettingsSubsection = 'defaults' | 'providers' | 'models';
export type KnowledgeSettingsSubsection = 'defaults' | 'embedding_models' | 'knowledge_bases';

const sections: { id: SettingsSection; label: string; icon: typeof Settings }[] = [
  { id: 'general', label: 'General', icon: Settings },
  { id: 'appearance', label: 'Appearance', icon: Palette },
  { id: 'llm', label: 'LLM', icon: SlidersHorizontal },
  { id: 'knowledge', label: 'Knowledge', icon: BrainCircuit },
  { id: 'agents', label: 'Agents', icon: Bot },
  { id: 'capabilities', label: 'Capabilities', icon: Boxes },
  { id: 'data', label: 'Data', icon: Database },
  { id: 'diagnostics', label: 'Diagnostics', icon: Activity },
  { id: 'developer', label: 'Developer', icon: Code2 },
  { id: 'about', label: 'About', icon: Info },
];

export function SettingsNav({
  activeSection,
  activeLlmSubsection = 'defaults',
  activeKnowledgeSubsection = 'defaults',
  onChange,
  onLlmSubsectionChange,
  onKnowledgeSubsectionChange,
}: {
  activeSection: SettingsSection;
  onChange: (section: SettingsSection) => void;
  activeLlmSubsection?: LlmSettingsSubsection;
  activeKnowledgeSubsection?: KnowledgeSettingsSubsection;
  onLlmSubsectionChange?: (subsection: LlmSettingsSubsection) => void;
  onKnowledgeSubsectionChange?: (subsection: KnowledgeSettingsSubsection) => void;
}) {
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
              <span>{section.label}</span>
            </button>
            {section.id === 'llm' && activeSection === 'llm' ? (
              <div className="settings-subnav" aria-label="LLM settings sections">
                <button
                  type="button"
                  className={activeLlmSubsection === 'defaults' ? 'active' : ''}
                  onClick={() => onLlmSubsectionChange?.('defaults')}
                >
                  <span>Defaults</span>
                </button>
                <button
                  type="button"
                  className={activeLlmSubsection === 'providers' ? 'active' : ''}
                  onClick={() => onLlmSubsectionChange?.('providers')}
                >
                  <span>Provider Profiles</span>
                </button>
                <button
                  type="button"
                  className={activeLlmSubsection === 'models' ? 'active' : ''}
                  onClick={() => onLlmSubsectionChange?.('models')}
                >
                  <span>Model Profiles</span>
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
                  <span>Defaults</span>
                </button>
                <button
                  type="button"
                  className={activeKnowledgeSubsection === 'embedding_models' ? 'active' : ''}
                  onClick={() => onKnowledgeSubsectionChange?.('embedding_models')}
                >
                  <span>Embedding Models</span>
                </button>
                <button
                  type="button"
                  className={activeKnowledgeSubsection === 'knowledge_bases' ? 'active' : ''}
                  onClick={() => onKnowledgeSubsectionChange?.('knowledge_bases')}
                >
                  <span>Knowledge Bases</span>
                </button>
              </div>
            ) : null}
          </div>
        );
      })}
    </nav>
  );
}
