import { Activity, Bot, Boxes, Code2, Database, Info, Settings, SlidersHorizontal } from 'lucide-react';

export type SettingsSection = 'general' | 'llm' | 'agents' | 'capabilities' | 'data' | 'diagnostics' | 'developer' | 'about';

const sections: { id: SettingsSection; label: string; icon: typeof Settings }[] = [
  { id: 'general', label: 'General', icon: Settings },
  { id: 'llm', label: 'LLM', icon: SlidersHorizontal },
  { id: 'agents', label: 'Agents', icon: Bot },
  { id: 'capabilities', label: 'Capabilities', icon: Boxes },
  { id: 'data', label: 'Data', icon: Database },
  { id: 'diagnostics', label: 'Diagnostics', icon: Activity },
  { id: 'developer', label: 'Developer', icon: Code2 },
  { id: 'about', label: 'About', icon: Info },
];

export function SettingsNav({
  activeSection,
  onChange,
}: {
  activeSection: SettingsSection;
  onChange: (section: SettingsSection) => void;
}) {
  return (
    <nav className="settings-nav" aria-label="Settings sections">
      {sections.map((section) => {
        const Icon = section.icon;
        return (
          <button
            key={section.id}
            type="button"
            className={activeSection === section.id ? 'active' : ''}
            onClick={() => onChange(section.id)}
          >
            <Icon size={16} />
            <span>{section.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
