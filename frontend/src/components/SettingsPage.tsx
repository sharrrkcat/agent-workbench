import { ArrowLeft, Bot, Boxes, Settings } from 'lucide-react';
import { ErrorBanner } from './ErrorBanner';
import { SettingsConsole } from './settings/SettingsConsole';
import type { SettingsSection } from './settings/SettingsNav';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function SettingsPage({ initialSection = 'general', onBack }: { initialSection?: SettingsSection; onBack: () => void }) {
  const { agentConfigs, capabilityConfigs } = useWorkbenchStore();

  return (
    <main className="settings-page">
      <header className="settings-page-header">
        <button className="back-button" type="button" onClick={onBack}>
          <ArrowLeft size={17} />
          Back to chat
        </button>
        <div className="settings-heading">
          <div className="settings-heading-icon">
            <Settings size={20} />
          </div>
          <div>
            <h1>Settings</h1>
            <p>Configure local agents, capabilities, and LLM connection details.</p>
          </div>
        </div>
        <div className="settings-page-stats" aria-label="Settings summary">
          <span>
            <Bot size={14} />
            {agentConfigs.length} agents
          </span>
          <span>
            <Boxes size={14} />
            {capabilityConfigs.length} capabilities
          </span>
        </div>
      </header>
      <ErrorBanner />
      <SettingsConsole initialSection={initialSection} />
    </main>
  );
}
