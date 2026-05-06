import { useCallback, useEffect, useMemo, useState } from 'react';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import { SettingsDetailPanel } from './SettingsDetailPanel';
import { SettingsNav, type SettingsSection } from './SettingsNav';
import { SettingsObjectList } from './SettingsObjectList';

export function SettingsConsole() {
  const { agents, commands, agentConfigs, capabilityConfigs, health } = useWorkbenchStore();
  const [activeSection, setActiveSection] = useState<SettingsSection>('llm');
  const [selectedAgentId, setSelectedAgentId] = useState<string>('');
  const [selectedCapabilityId, setSelectedCapabilityId] = useState<string>('llm');
  const [activeDetailTab, setActiveDetailTab] = useState('overview');
  const [detailDirty, setDetailDirty] = useState(false);

  useEffect(() => {
    if (!selectedAgentId && agentConfigs.length) {
      setSelectedAgentId(agentConfigs[0].agent_id);
    }
  }, [agentConfigs, selectedAgentId]);

  useEffect(() => {
    if (!selectedCapabilityId && capabilityConfigs.length) {
      setSelectedCapabilityId(capabilityConfigs[0].capability_id);
    }
  }, [capabilityConfigs, selectedCapabilityId]);

  const confirmDirtyNavigation = useCallback(() => {
    if (!detailDirty) return true;
    return window.confirm('You have unsaved settings changes. Discard them and continue?');
  }, [detailDirty]);

  function changeSection(section: SettingsSection) {
    if (section === activeSection) return;
    if (!confirmDirtyNavigation()) return;
    setDetailDirty(false);
    setActiveSection(section);
    setActiveDetailTab('overview');
    if (section === 'agents' && !selectedAgentId && agentConfigs[0]) {
      setSelectedAgentId(agentConfigs[0].agent_id);
    }
    if ((section === 'capabilities' || section === 'llm') && !selectedCapabilityId && capabilityConfigs[0]) {
      setSelectedCapabilityId(section === 'llm' ? 'llm' : capabilityConfigs[0].capability_id);
    }
  }

  function selectAgent(agentId: string) {
    if (agentId === selectedAgentId) return;
    if (!confirmDirtyNavigation()) return;
    setDetailDirty(false);
    setSelectedAgentId(agentId);
    setActiveDetailTab('overview');
  }

  function selectCapability(capabilityId: string) {
    if (capabilityId === selectedCapabilityId) return;
    if (!confirmDirtyNavigation()) return;
    setDetailDirty(false);
    setSelectedCapabilityId(capabilityId);
    setActiveDetailTab('overview');
  }

  const selectedAgentConfig = agentConfigs.find((config) => config.agent_id === selectedAgentId) || agentConfigs[0];
  const selectedAgent = agents.find((agent) => agent.id === selectedAgentConfig?.agent_id);
  const selectedCapabilityConfig = useMemo(() => {
    if (activeSection === 'llm') {
      return capabilityConfigs.find((config) => config.capability_id === 'llm') || capabilityConfigs[0];
    }
    return capabilityConfigs.find((config) => config.capability_id === selectedCapabilityId) || capabilityConfigs[0];
  }, [activeSection, capabilityConfigs, selectedCapabilityId]);

  return (
    <div className="settings-console">
      <SettingsNav activeSection={activeSection} onChange={changeSection} />
      <SettingsObjectList
        section={activeSection}
        agentConfigs={agentConfigs}
        capabilityConfigs={capabilityConfigs}
        selectedAgentId={selectedAgentConfig?.agent_id}
        selectedCapabilityId={selectedCapabilityConfig?.capability_id}
        onSelectAgent={selectAgent}
        onSelectCapability={selectCapability}
      />
      <SettingsDetailPanel
        section={activeSection}
        selectedAgent={selectedAgent}
        selectedAgentConfig={selectedAgentConfig}
        selectedCapabilityConfig={selectedCapabilityConfig}
        commands={commands}
        health={health}
        activeTab={activeDetailTab}
        onTabChange={setActiveDetailTab}
        onDirtyChange={setDetailDirty}
      />
    </div>
  );
}
