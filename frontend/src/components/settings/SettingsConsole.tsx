import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../api/client';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { EmbeddingModelProfile, KnowledgeBase, LlmProfile, LlmProviderProfile, RerankerModelProfile, Worldbook } from '../../types';
import { SettingsDetailPanel } from './SettingsDetailPanel';
import { SettingsNav, type KnowledgeSettingsSubsection, type LlmSettingsSubsection, type SettingsInitialTarget, type SettingsSection, type WorldbookSettingsSubsection } from './SettingsNav';
import { SettingsObjectList, type AppearanceSettingsCategory, type GeneralSettingsCategory } from './SettingsObjectList';

export function SettingsConsole({ initialSection = 'general', initialTarget }: { initialSection?: SettingsSection; initialTarget?: SettingsInitialTarget }) {
  const { agents, commands, agentConfigs, capabilityConfigs, health } = useWorkbenchStore();
  const { t } = useTranslation('settings');
  const [activeSection, setActiveSection] = useState<SettingsSection>(initialTarget?.section || initialSection);
  const [selectedAgentId, setSelectedAgentId] = useState<string>('');
  const [selectedCapabilityId, setSelectedCapabilityId] = useState<string>('');
  const [llmProfiles, setLlmProfiles] = useState<LlmProfile[]>([]);
  const [llmProviderProfiles, setLlmProviderProfiles] = useState<LlmProviderProfile[]>([]);
  const [selectedLlmItemId, setSelectedLlmItemId] = useState<string>('');
  const [selectedLlmSubsection, setSelectedLlmSubsection] = useState<LlmSettingsSubsection>('providers');
  const [embeddingProfiles, setEmbeddingProfiles] = useState<EmbeddingModelProfile[]>([]);
  const [rerankerProfiles, setRerankerProfiles] = useState<RerankerModelProfile[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKnowledgeSubsection, setSelectedKnowledgeSubsection] = useState<KnowledgeSettingsSubsection>('defaults');
  const [selectedKnowledgeItemId, setSelectedKnowledgeItemId] = useState<string>('global');
  const [worldbooks, setWorldbooks] = useState<Worldbook[]>([]);
  const [selectedWorldbookSubsection, setSelectedWorldbookSubsection] = useState<WorldbookSettingsSubsection>('defaults');
  const [selectedWorldbookItemId, setSelectedWorldbookItemId] = useState<string>('global');
  const [generalCategory, setGeneralCategory] = useState<GeneralSettingsCategory>('files');
  const [appearanceCategory, setAppearanceCategory] = useState<AppearanceSettingsCategory>('pet');
  const [activeDetailTab, setActiveDetailTab] = useState('overview');
  const [detailDirty, setDetailDirty] = useState(false);

  useEffect(() => {
    void refreshLlmProfiles().catch(() => undefined);
  }, []);

  useEffect(() => {
    if (initialTarget?.section === 'models' && initialTarget.llmSubsection) {
      setSelectedLlmSubsection(initialTarget.llmSubsection);
      if (initialTarget.llmSubsection === 'providers') {
        setSelectedLlmItemId(llmProviderProfiles[0] ? `provider:${llmProviderProfiles[0].id}` : '');
      } else if (initialTarget.llmSubsection === 'models') {
        setSelectedLlmItemId(llmProfiles[0]?.id || '');
      }
    }
    if (initialTarget?.section === 'models' && initialTarget.llmSubsection === 'embedding_models') {
      setSelectedKnowledgeSubsection('embedding_models');
      setSelectedKnowledgeItemId('');
    }
    if (initialTarget?.section === 'knowledge' && initialTarget.knowledgeSubsection) {
      setSelectedKnowledgeSubsection(initialTarget.knowledgeSubsection);
      setSelectedKnowledgeItemId(initialTarget.knowledgeSubsection === 'defaults' ? 'global' : '');
    }
    if (initialTarget?.section === 'worldbook' && initialTarget.worldbookSubsection) {
      setSelectedWorldbookSubsection(initialTarget.worldbookSubsection);
      setSelectedWorldbookItemId(initialTarget.worldbookSubsection === 'defaults' ? 'global' : '');
    }
  }, [initialTarget?.knowledgeSubsection, initialTarget?.llmSubsection, initialTarget?.section, initialTarget?.worldbookSubsection]);

  useEffect(() => {
    if (activeSection === 'knowledge' || activeSection === 'models') {
      void refreshKnowledgeObjects().catch(() => undefined);
    }
    if (activeSection === 'worldbook') {
      void refreshWorldbookObjects().catch(() => undefined);
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
    if (section === 'models' && !selectedLlmItemId) {
      setSelectedLlmItemId(llmProviderProfiles[0] ? `provider:${llmProviderProfiles[0].id}` : '');
    }
    if (section === 'models') {
      setSelectedLlmSubsection('providers');
      setSelectedLlmItemId(llmProviderProfiles[0] ? `provider:${llmProviderProfiles[0].id}` : '');
      void refreshKnowledgeObjects().catch(() => undefined);
    }
    if (section === 'general') {
      setGeneralCategory('files');
    }
    if (section === 'appearance') {
      setAppearanceCategory('pet');
    }
    if (section === 'knowledge') {
      setSelectedKnowledgeSubsection('defaults');
      setSelectedKnowledgeItemId('global');
      void refreshKnowledgeObjects().catch(() => undefined);
    }
    if (section === 'worldbook') {
      setSelectedWorldbookSubsection('defaults');
      setSelectedWorldbookItemId('global');
      void refreshWorldbookObjects().catch(() => undefined);
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
    if (nextSelectedId === 'new' || nextSelectedId === 'new-provider') {
      setSelectedLlmItemId(nextSelectedId);
      return;
    }
    if (nextSelectedId?.startsWith('provider:') && providerProfiles.some((profile) => `provider:${profile.id}` === nextSelectedId)) {
      setSelectedLlmItemId(nextSelectedId);
      return;
    }
    if (selectedLlmItemId.startsWith('provider:') && !providerProfiles.some((profile) => `provider:${profile.id}` === selectedLlmItemId)) {
      setSelectedLlmItemId(providerProfiles[0] ? `provider:${providerProfiles[0].id}` : '');
      return;
    }
    if (nextSelectedId && profiles.some((profile) => profile.id === nextSelectedId)) {
      setSelectedLlmItemId(nextSelectedId);
      return;
    }
    if (selectedLlmItemId && selectedLlmItemId !== 'new' && !selectedLlmItemId.startsWith('provider:') && !profiles.some((profile) => profile.id === selectedLlmItemId)) {
      setSelectedLlmItemId(profiles[0]?.id || '');
    }
  }

  async function refreshKnowledgeObjects(nextSelectedId?: string) {
    const [profiles, rerankers, bases] = await Promise.all([api.listEmbeddingModels(), api.listRerankerModels(), api.listKnowledgeBases()]);
    setEmbeddingProfiles(profiles);
    setRerankerProfiles(rerankers);
    setKnowledgeBases(bases);
    if (nextSelectedId) {
      setSelectedKnowledgeItemId(nextSelectedId);
      return;
    }
    if (selectedLlmSubsection === 'reranker_models' && !selectedKnowledgeItemId) {
      setSelectedKnowledgeItemId(rerankers[0]?.id || '');
    }
    if (selectedKnowledgeSubsection === 'embedding_models' && !selectedKnowledgeItemId) {
      setSelectedKnowledgeItemId(profiles[0]?.id || '');
    }
    if (selectedKnowledgeSubsection === 'knowledge_bases' && !selectedKnowledgeItemId) {
      setSelectedKnowledgeItemId(bases[0]?.id || '');
    }
    if (selectedKnowledgeSubsection === 'embedding_models' && selectedKnowledgeItemId && selectedKnowledgeItemId !== 'new' && !profiles.some((profile) => profile.id === selectedKnowledgeItemId)) {
      setSelectedKnowledgeItemId(profiles[0]?.id || '');
    }
    if (selectedLlmSubsection === 'reranker_models' && selectedKnowledgeItemId && selectedKnowledgeItemId !== 'new' && !rerankers.some((profile) => profile.id === selectedKnowledgeItemId)) {
      setSelectedKnowledgeItemId(rerankers[0]?.id || '');
    }
    if (selectedKnowledgeSubsection === 'knowledge_bases' && selectedKnowledgeItemId && selectedKnowledgeItemId !== 'new' && !bases.some((base) => base.id === selectedKnowledgeItemId)) {
      setSelectedKnowledgeItemId(bases[0]?.id || '');
    }
  }

  async function refreshWorldbookObjects(nextSelectedId?: string) {
    const items = await api.listWorldbooks();
    setWorldbooks(items);
    if (nextSelectedId) {
      setSelectedWorldbookItemId(nextSelectedId);
      return;
    }
    if (selectedWorldbookSubsection === 'worldbooks' && !selectedWorldbookItemId) {
      setSelectedWorldbookItemId(items[0]?.id || '');
    }
    if (selectedWorldbookSubsection === 'worldbooks' && selectedWorldbookItemId && selectedWorldbookItemId !== 'new' && !items.some((item) => item.id === selectedWorldbookItemId)) {
      setSelectedWorldbookItemId(items[0]?.id || '');
    }
  }

  function changeLlmSubsection(subsection: LlmSettingsSubsection) {
    if (subsection === selectedLlmSubsection) return;
    if (!confirmDirtyNavigation()) return;
    setDetailDirty(false);
    setSelectedLlmSubsection(subsection);
    if (subsection === 'providers') {
      const providerId = selectedLlmItemId.startsWith('provider:') ? selectedLlmItemId : llmProviderProfiles[0] ? `provider:${llmProviderProfiles[0].id}` : '';
      setSelectedLlmItemId(providerId);
    } else if (subsection === 'models') {
      const modelId = selectedLlmItemId && !selectedLlmItemId.startsWith('provider:') && selectedLlmItemId !== 'global' && selectedLlmItemId !== 'new-provider'
        ? selectedLlmItemId
        : llmProfiles[0]?.id || '';
      setSelectedLlmItemId(modelId);
    } else if (subsection === 'embedding_models') {
      setSelectedKnowledgeSubsection('embedding_models');
      setSelectedKnowledgeItemId(embeddingProfiles[0]?.id || '');
    } else if (subsection === 'reranker_models') {
      setSelectedKnowledgeItemId(rerankerProfiles[0]?.id || '');
    }
  }

  function goToEmbeddingProfiles() {
    if (!confirmDirtyNavigation()) return;
    setDetailDirty(false);
    setActiveSection('models');
    setSelectedLlmSubsection('embedding_models');
    setSelectedKnowledgeSubsection('embedding_models');
    setSelectedKnowledgeItemId(embeddingProfiles[0]?.id || '');
    void refreshKnowledgeObjects().catch(() => undefined);
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

  function changeWorldbookSubsection(subsection: WorldbookSettingsSubsection) {
    if (subsection === selectedWorldbookSubsection) return;
    if (!confirmDirtyNavigation()) return;
    setDetailDirty(false);
    setSelectedWorldbookSubsection(subsection);
    setSelectedWorldbookItemId(subsection === 'defaults' ? 'global' : worldbooks[0]?.id || '');
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

  function selectWorldbookItem(itemId: string) {
    if (itemId === selectedWorldbookItemId) return;
    if (!confirmDirtyNavigation()) return;
    setDetailDirty(false);
    setSelectedWorldbookItemId(itemId);
  }

  const selectedAgentConfig = agentConfigs.find((config) => config.agent_id === selectedAgentId) || agentConfigs[0];
  const selectedAgent = agents.find((agent) => agent.id === selectedAgentConfig?.agent_id);
  const selectedCapabilityConfig = useMemo(() => {
    if (activeSection === 'models') {
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
        activeWorldbookSubsection={selectedWorldbookSubsection}
        onChange={changeSection}
        onLlmSubsectionChange={changeLlmSubsection}
        onKnowledgeSubsectionChange={changeKnowledgeSubsection}
        onWorldbookSubsectionChange={changeWorldbookSubsection}
      />
      <SettingsObjectList
        section={activeSection}
        llmSubsection={selectedLlmSubsection}
        knowledgeSubsection={selectedKnowledgeSubsection}
        worldbookSubsection={selectedWorldbookSubsection}
        generalCategory={generalCategory}
        appearanceCategory={appearanceCategory}
        agentConfigs={agentConfigs}
        capabilityConfigs={capabilityConfigs}
        selectedAgentId={selectedAgentConfig?.agent_id}
        selectedCapabilityId={selectedCapabilityConfig?.capability_id}
        llmProfiles={llmProfiles}
        llmProviderProfiles={llmProviderProfiles}
        selectedLlmItemId={selectedLlmItemId}
        embeddingProfiles={embeddingProfiles}
        rerankerProfiles={rerankerProfiles}
        knowledgeBases={knowledgeBases}
        selectedKnowledgeItemId={selectedKnowledgeItemId}
        worldbooks={worldbooks}
        selectedWorldbookItemId={selectedWorldbookItemId}
        onSelectGeneralCategory={setGeneralCategory}
        onSelectAppearanceCategory={setAppearanceCategory}
        onSelectAgent={selectAgent}
        onSelectCapability={selectCapability}
        onSelectLlmItem={selectLlmItem}
        onSelectKnowledgeItem={selectKnowledgeItem}
        onSelectWorldbookItem={selectWorldbookItem}
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
        rerankerProfiles={rerankerProfiles}
        selectedLlmItemId={selectedLlmItemId}
        llmSubsection={selectedLlmSubsection}
        generalCategory={generalCategory}
        appearanceCategory={appearanceCategory}
        knowledgeSubsection={selectedKnowledgeSubsection}
        selectedKnowledgeItemId={selectedKnowledgeItemId}
        worldbookSubsection={selectedWorldbookSubsection}
        selectedWorldbookItemId={selectedWorldbookItemId}
        onLlmProfilesChanged={refreshLlmProfiles}
        onKnowledgeObjectsChanged={refreshKnowledgeObjects}
        onWorldbookObjectsChanged={refreshWorldbookObjects}
        onSelectGeneralCategory={setGeneralCategory}
        onManageEmbeddingProfiles={goToEmbeddingProfiles}
        activeTab={activeDetailTab}
        onTabChange={setActiveDetailTab}
        onDirtyChange={setDetailDirty}
      />
    </div>
  );
}
