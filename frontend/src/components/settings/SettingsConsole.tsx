import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../api/client';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { EmbeddingModelProfile, KnowledgeBase, LlmProfile, LlmProviderProfile } from '../../types';
import { SettingsDetailPanel } from './SettingsDetailPanel';
import { SettingsNav, type KnowledgeSettingsSubsection, type LlmSettingsSubsection, type SettingsSection } from './SettingsNav';
import { SettingsObjectList, type GeneralSettingsCategory } from './SettingsObjectList';

export function SettingsConsole({ initialSection = 'general' }: { initialSection?: SettingsSection }) {
  const { agents, commands, agentConfigs, capabilityConfigs, health } = useWorkbenchStore();
  const { t } = useTranslation('settings');
  const [activeSection, setActiveSection] = useState<SettingsSection>(initialSection);
  const [selectedAgentId, setSelectedAgentId] = useState<string>('');
  const [selectedCapabilityId, setSelectedCapabilityId] = useState<string>('');
  const [llmProfiles, setLlmProfiles] = useState<LlmProfile[]>([]);
  const [llmProviderProfiles, setLlmProviderProfiles] = useState<LlmProviderProfile[]>([]);
  const [selectedLlmItemId, setSelectedLlmItemId] = useState<string>('global');
  const [selectedLlmSubsection, setSelectedLlmSubsection] = useState<LlmSettingsSubsection>('defaults');
  const [embeddingProfiles, setEmbeddingProfiles] = useState<EmbeddingModelProfile[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKnowledgeSubsection, setSelectedKnowledgeSubsection] = useState<KnowledgeSettingsSubsection>('defaults');
  const [selectedKnowledgeItemId, setSelectedKnowledgeItemId] = useState<string>('global');
  const [generalCategory, setGeneralCategory] = useState<GeneralSettingsCategory>('files');
  const [activeDetailTab, setActiveDetailTab] = useState('overview');
  const [detailDirty, setDetailDirty] = useState(false);

  useEffect(() => {
    void refreshLlmProfiles().catch(() => undefined);
  }, []);

  useEffect(() => {
    if (activeSection === 'knowledge') {
      void refreshKnowledgeObjects().catch(() => undefined);
    }
  }, [activeSection]);

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
    return window.confirm(t('confirmDiscard'));
  }, [detailDirty, t]);

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
    if (section === 'general') {
      setGeneralCategory('files');
    }
    if (section === 'knowledge') {
      setSelectedKnowledgeSubsection('defaults');
      setSelectedKnowledgeItemId('global');
      void refreshKnowledgeObjects().catch(() => undefined);
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

  async function refreshKnowledgeObjects(nextSelectedId?: string) {
    const [profiles, bases] = await Promise.all([api.listEmbeddingModels(), api.listKnowledgeBases()]);
    setEmbeddingProfiles(profiles);
    setKnowledgeBases(bases);
    if (nextSelectedId) {
      setSelectedKnowledgeItemId(nextSelectedId);
      return;
    }
    if (selectedKnowledgeSubsection === 'embedding_models' && selectedKnowledgeItemId && selectedKnowledgeItemId !== 'new' && !profiles.some((profile) => profile.id === selectedKnowledgeItemId)) {
      setSelectedKnowledgeItemId(profiles[0]?.id || '');
    }
    if (selectedKnowledgeSubsection === 'knowledge_bases' && selectedKnowledgeItemId && selectedKnowledgeItemId !== 'new' && !bases.some((base) => base.id === selectedKnowledgeItemId)) {
      setSelectedKnowledgeItemId(bases[0]?.id || '');
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

  function changeKnowledgeSubsection(subsection: KnowledgeSettingsSubsection) {
    if (subsection === selectedKnowledgeSubsection) return;
    if (!confirmDirtyNavigation()) return;
    setDetailDirty(false);
    setSelectedKnowledgeSubsection(subsection);
    if (subsection === 'defaults') {
      setSelectedKnowledgeItemId('global');
    } else if (subsection === 'embedding_models') {
      setSelectedKnowledgeItemId(embeddingProfiles[0]?.id || '');
    } else {
      setSelectedKnowledgeItemId(knowledgeBases[0]?.id || '');
    }
  }

  function selectLlmItem(itemId: string) {
    if (itemId === selectedLlmItemId) return;
    if (!confirmDirtyNavigation()) return;
    setDetailDirty(false);
    setSelectedLlmItemId(itemId);
  }

  function selectKnowledgeItem(itemId: string) {
    if (itemId === selectedKnowledgeItemId) return;
    if (!confirmDirtyNavigation()) return;
    setDetailDirty(false);
    setSelectedKnowledgeItemId(itemId);
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
        activeKnowledgeSubsection={selectedKnowledgeSubsection}
        onChange={changeSection}
        onLlmSubsectionChange={changeLlmSubsection}
        onKnowledgeSubsectionChange={changeKnowledgeSubsection}
      />
      <SettingsObjectList
        section={activeSection}
        llmSubsection={selectedLlmSubsection}
        knowledgeSubsection={selectedKnowledgeSubsection}
        generalCategory={generalCategory}
        agentConfigs={agentConfigs}
        capabilityConfigs={capabilityConfigs}
        selectedAgentId={selectedAgentConfig?.agent_id}
        selectedCapabilityId={selectedCapabilityConfig?.capability_id}
        llmProfiles={llmProfiles}
        llmProviderProfiles={llmProviderProfiles}
        selectedLlmItemId={selectedLlmItemId}
        embeddingProfiles={embeddingProfiles}
        knowledgeBases={knowledgeBases}
        selectedKnowledgeItemId={selectedKnowledgeItemId}
        onSelectGeneralCategory={setGeneralCategory}
        onSelectAgent={selectAgent}
        onSelectCapability={selectCapability}
        onSelectLlmItem={selectLlmItem}
        onSelectKnowledgeItem={selectKnowledgeItem}
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
        generalCategory={generalCategory}
        knowledgeSubsection={selectedKnowledgeSubsection}
        selectedKnowledgeItemId={selectedKnowledgeItemId}
        onLlmProfilesChanged={refreshLlmProfiles}
        onKnowledgeObjectsChanged={refreshKnowledgeObjects}
        activeTab={activeDetailTab}
        onTabChange={setActiveDetailTab}
        onDirtyChange={setDetailDirty}
      />
    </div>
  );
}
