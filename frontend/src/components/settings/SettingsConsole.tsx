import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { LlmProfile, LlmProviderProfile } from '../../types';
import { SettingsDetailPanel } from './SettingsDetailPanel';
import { SettingsNav, type LlmSettingsSubsection, type SettingsSection } from './SettingsNav';
import { SettingsObjectList } from './SettingsObjectList';

export function SettingsConsole({ initialSection = 'general' }: { initialSection?: SettingsSection }) {
  const { agents, commands, agentConfigs, capabilityConfigs, health } = useWorkbenchStore();
  const [activeSection, setActiveSection] = useState<SettingsSection>(initialSection);
  const [selectedAgentId, setSelectedAgentId] = useState<string>('');
  const [selectedCapabilityId, setSelectedCapabilityId] = useState<string>('');
  const [llmProfiles, setLlmProfiles] = useState<LlmProfile[]>([]);
  const [llmProviderProfiles, setLlmProviderProfiles] = useState<LlmProviderProfile[]>([]);
  const [selectedLlmItemId, setSelectedLlmItemId] = useState<string>('global');
  const [selectedLlmSubsection, setSelectedLlmSubsection] = useState<LlmSettingsSubsection>('defaults');
  const [activeDetailTab, setActiveDetailTab] = useState('overview');
  const [detailDirty, setDetailDirty] = useState(false);

  useEffect(() => {
    void refreshLlmProfiles().catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!selectedAgentId && agentConfigs.length) {
      setSelectedAgentId(agentConfigs[0].agent_id);
    }
  }, [agentConfigs, selectedAgentId]);

  useEffect(() => {
    if (!capabilityConfigs.length) return;
    if (!selectedCapabilityId || !capabilityConfigs.some((config) => config.capability_id === selectedCapabilityId)) {
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
    if (section === 'capabilities' && !selectedCapabilityId && capabilityConfigs[0]) {
      setSelectedCapabilityId(capabilityConfigs[0].capability_id);
    }
    if (section === 'llm' && !selectedLlmItemId) {
      setSelectedLlmItemId('global');
    }
    if (section === 'llm') {
      setSelectedLlmSubsection('defaults');
      setSelectedLlmItemId('global');
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

  async function refreshLlmProfiles(nextSelectedId?: string) {
    const [profiles, providerProfiles] = await Promise.all([api.listLlmProfiles(), api.listLlmProviderProfiles()]);
    setLlmProfiles(profiles);
    setLlmProviderProfiles(providerProfiles);
    if (nextSelectedId === 'global' || nextSelectedId === 'new' || nextSelectedId === 'new-provider') {
      setSelectedLlmItemId(nextSelectedId);
      return;
    }
    if (nextSelectedId?.startsWith('provider:') && providerProfiles.some((profile) => `provider:${profile.id}` === nextSelectedId)) {
      setSelectedLlmItemId(nextSelectedId);
      return;
    }
    if (selectedLlmItemId.startsWith('provider:') && !providerProfiles.some((profile) => `provider:${profile.id}` === selectedLlmItemId)) {
      setSelectedLlmItemId('global');
      return;
    }
    if (nextSelectedId && profiles.some((profile) => profile.id === nextSelectedId)) {
      setSelectedLlmItemId(nextSelectedId);
      return;
    }
    if (selectedLlmItemId !== 'global' && selectedLlmItemId !== 'new' && !profiles.some((profile) => profile.id === selectedLlmItemId)) {
      setSelectedLlmItemId('global');
    }
  }

  function changeLlmSubsection(subsection: LlmSettingsSubsection) {
    if (subsection === selectedLlmSubsection) return;
    if (!confirmDirtyNavigation()) return;
    setDetailDirty(false);
    setSelectedLlmSubsection(subsection);
    if (subsection === 'defaults') {
      setSelectedLlmItemId('global');
    } else if (subsection === 'providers') {
      const providerId = selectedLlmItemId.startsWith('provider:') ? selectedLlmItemId : llmProviderProfiles[0] ? `provider:${llmProviderProfiles[0].id}` : '';
      setSelectedLlmItemId(providerId);
    } else {
      const modelId = selectedLlmItemId && !selectedLlmItemId.startsWith('provider:') && selectedLlmItemId !== 'global' && selectedLlmItemId !== 'new-provider'
        ? selectedLlmItemId
        : llmProfiles[0]?.id || '';
      setSelectedLlmItemId(modelId);
    }
  }

  function selectLlmItem(itemId: string) {
    if (itemId === selectedLlmItemId) return;
    if (!confirmDirtyNavigation()) return;
    setDetailDirty(false);
    setSelectedLlmItemId(itemId);
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
      <SettingsNav
        activeSection={activeSection}
        activeLlmSubsection={selectedLlmSubsection}
        onChange={changeSection}
        onLlmSubsectionChange={changeLlmSubsection}
      />
      <SettingsObjectList
        section={activeSection}
        llmSubsection={selectedLlmSubsection}
        agentConfigs={agentConfigs}
        capabilityConfigs={capabilityConfigs}
        selectedAgentId={selectedAgentConfig?.agent_id}
        selectedCapabilityId={selectedCapabilityConfig?.capability_id}
        llmProfiles={llmProfiles}
        llmProviderProfiles={llmProviderProfiles}
        selectedLlmItemId={selectedLlmItemId}
        onSelectAgent={selectAgent}
        onSelectCapability={selectCapability}
        onSelectLlmItem={selectLlmItem}
      />
      <SettingsDetailPanel
        section={activeSection}
        selectedAgent={selectedAgent}
        selectedAgentConfig={selectedAgentConfig}
        selectedCapabilityConfig={selectedCapabilityConfig}
        commands={commands}
        health={health}
        llmProfiles={llmProfiles}
        llmProviderProfiles={llmProviderProfiles}
        selectedLlmItemId={selectedLlmItemId}
        llmSubsection={selectedLlmSubsection}
        onLlmProfilesChanged={refreshLlmProfiles}
        activeTab={activeDetailTab}
        onTabChange={setActiveDetailTab}
        onDirtyChange={setDetailDirty}
      />
    </div>
  );
}
