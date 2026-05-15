import { ArrowUpDown, BrainCircuit, ChevronDown, Clipboard, FileText, FolderPlus, Loader2, Play, RefreshCw, Save, Search, Trash2, Upload, X } from 'lucide-react';
import { ChangeEvent, DragEvent, FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { api } from '../../api/client';
import type { EmbeddingModelProfile, EmbeddingModelProfileInput, KnowledgeBase, KnowledgeBaseInput, KnowledgeModelScan, KnowledgeOrigin, KnowledgeOriginFolderSuggestion, KnowledgeSearchResponse, KnowledgeSettings, KnowledgeSource, KnowledgeSourceChunk, KnowledgeSourcePreview } from '../../types';
import { stableConfigString } from './configUtils';
import { DetailTabs } from './DetailTabs';
import type { KnowledgeSettingsCategory } from './SettingsObjectList';
import { SettingsApiError, toSettingsError, type SettingsErrorValue } from './SettingsApiError';
import { MiniToggle, ToggleSwitch } from './ToggleSwitch';
import { getKnowledgeIndexStatusLabel, getKnowledgeOriginStatusLabel, getKnowledgeSourceStatusLabel } from '../../i18n/formatters';
import { AppModal, StatusChip } from '../ui';

type FormMode = 'list' | 'new' | string;
type SourceSortKey = 'title' | 'source_type' | 'folder_path' | 'chunks' | 'status' | 'indexed_at';
type SortDirection = 'asc' | 'desc';
type KnowledgeDefaultsTab = 'overview' | 'models' | 'retrieval' | 'chunking' | 'context' | 'download';
type KnowledgeBaseTab = 'config' | 'manage_sources' | 'source_list' | 'search';
type SourceModal = 'create_origin' | 'import_files' | 'paste_text' | null;
type DownloadModelType = 'embedding' | 'reranker';
type ChunkProfile = 'plain_text' | 'markdown_document' | 'markdown_collection' | 'markdown_auto';
type EmbeddingProfilePreset = {
  name: string;
  alias: string;
  dimension?: number;
  normalize: boolean;
  document_instruction?: string;
  query_instruction?: string;
};

const KNOWLEDGE_INSTALL_COMMANDS = [
  { key: 'basicCpu', command: 'uv pip install sentence-transformers torch transformers' },
  { key: 'cuda128', command: 'uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128\nuv pip install sentence-transformers transformers' },
  { key: 'cuda126', command: 'uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126\nuv pip install sentence-transformers transformers' },
] as const;

const KNOWLEDGE_MODEL_PRESETS: {
  type: DownloadModelType;
  group: 'recommendedEmbeddings' | 'advancedEmbeddings' | 'recommendedRerankers' | 'advancedRerankers';
  modelId: string;
  target: string;
  noteKey: string;
  estimatedVramKey: string;
  profile?: EmbeddingProfilePreset;
}[] = [
  {
    type: 'embedding',
    group: 'recommendedEmbeddings',
    modelId: 'sentence-transformers/all-MiniLM-L6-v2',
    target: 'all-MiniLM-L6-v2',
    noteKey: 'allMiniLm',
    estimatedVramKey: 'under1gb',
    profile: { name: 'all-MiniLM-L6-v2', alias: 'all-minilm-l6-v2', dimension: 384, normalize: true },
  },
  {
    type: 'embedding',
    group: 'recommendedEmbeddings',
    modelId: 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
    target: 'paraphrase-multilingual-MiniLM-L12-v2',
    noteKey: 'paraphraseMultilingualMiniLm',
    estimatedVramKey: 'about1gb',
    profile: { name: 'paraphrase-multilingual-MiniLM-L12-v2', alias: 'paraphrase-multilingual-minilm-l12-v2', dimension: 384, normalize: true },
  },
  {
    type: 'embedding',
    group: 'recommendedEmbeddings',
    modelId: 'google/embeddinggemma-300m',
    target: 'embeddinggemma-300m',
    noteKey: 'embeddingGemma',
    estimatedVramKey: 'about1to2gb',
    profile: { name: 'embeddinggemma-300m', alias: 'embeddinggemma-300m', normalize: true },
  },
  {
    type: 'embedding',
    group: 'recommendedEmbeddings',
    modelId: 'BAAI/bge-m3',
    target: 'bge-m3',
    noteKey: 'bgeM3',
    estimatedVramKey: 'about2to4gb',
    profile: { name: 'bge-m3', alias: 'bge-m3', dimension: 1024, normalize: true },
  },
  {
    type: 'embedding',
    group: 'advancedEmbeddings',
    modelId: 'Qwen/Qwen3-Embedding-0.6B',
    target: 'Qwen3-Embedding-0.6B',
    noteKey: 'qwen3Embedding06b',
    estimatedVramKey: 'about2to4gb',
    profile: {
      name: 'Qwen3 Embedding 0.6B',
      alias: 'qwen3-embedding-0-6b',
      dimension: 1024,
      normalize: true,
      document_instruction: 'Represent this document for retrieval:',
      query_instruction: 'Represent this query for retrieving relevant documents:',
    },
  },
  {
    type: 'embedding',
    group: 'advancedEmbeddings',
    modelId: 'jinaai/jina-embeddings-v3',
    target: 'jina-embeddings-v3',
    noteKey: 'jinaEmbeddingsV3',
    estimatedVramKey: 'about2to4gb',
    profile: { name: 'jina-embeddings-v3', alias: 'jina-embeddings-v3', dimension: 1024, normalize: true },
  },
  {
    type: 'embedding',
    group: 'advancedEmbeddings',
    modelId: 'nomic-ai/nomic-embed-text-v1.5',
    target: 'nomic-embed-text-v1.5',
    noteKey: 'nomicEmbedTextV15',
    estimatedVramKey: 'about1to2gb',
    profile: {
      name: 'nomic-embed-text-v1.5',
      alias: 'nomic-embed-text-v1-5',
      dimension: 768,
      normalize: true,
      document_instruction: 'search_document:',
      query_instruction: 'search_query:',
    },
  },
  {
    type: 'embedding',
    group: 'advancedEmbeddings',
    modelId: 'mixedbread-ai/mxbai-embed-large-v1',
    target: 'mxbai-embed-large-v1',
    noteKey: 'mxbaiEmbedLarge',
    estimatedVramKey: 'about15to3gb',
    profile: { name: 'mxbai-embed-large-v1', alias: 'mxbai-embed-large-v1', dimension: 1024, normalize: true },
  },
  {
    type: 'reranker',
    group: 'recommendedRerankers',
    modelId: 'BAAI/bge-reranker-v2-m3',
    target: 'bge-reranker-v2-m3',
    noteKey: 'bgeRerankerV2M3',
    estimatedVramKey: 'about2to4gb',
  },
  {
    type: 'reranker',
    group: 'advancedRerankers',
    modelId: 'Qwen/Qwen3-Reranker-0.6B',
    target: 'Qwen3-Reranker-0.6B',
    noteKey: 'qwen3Reranker06b',
    estimatedVramKey: 'about2to5gb',
  },
];

const KNOWLEDGE_MODEL_PRESET_GROUPS = [
  'recommendedEmbeddings',
  'advancedEmbeddings',
  'recommendedRerankers',
  'advancedRerankers',
] as const;

const defaultEmbeddingProfile: Partial<EmbeddingModelProfile> = {
  name: '',
  alias: '',
  model_path: '',
  dimension: null,
  normalize: true,
  document_instruction: '',
  query_instruction: '',
  enabled: true,
  notes: '',
};

const defaultKnowledgeBase: Partial<KnowledgeBase> = {
  name: '',
  description: '',
  aliases_text: '',
  embedding_model_profile_id: '',
  enabled: true,
  chunk_size_override: null,
  chunk_overlap_override: null,
  vector_candidate_k_override: null,
  keyword_candidate_k_override: null,
  final_top_k_override: null,
  max_context_chars_override: null,
  default_chunk_profile: 'markdown_auto',
};

const CHUNK_PROFILES: ChunkProfile[] = ['markdown_auto', 'markdown_document', 'markdown_collection', 'plain_text'];

export function KnowledgeSettingsDetail({
  category,
  selectedItemId = 'global',
  onObjectsChanged,
  onDirtyChange,
}: {
  category: KnowledgeSettingsCategory;
  selectedItemId?: string;
  onObjectsChanged?: (selectedItemId?: string) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation(['knowledge', 'common', 'status']);
  const [settings, setSettings] = useState<KnowledgeSettings | null>(null);
  const [values, setValues] = useState<KnowledgeSettings | null>(null);
  const [scan, setScan] = useState<KnowledgeModelScan | null>(null);
  const [embeddingProfiles, setEmbeddingProfiles] = useState<EmbeddingModelProfile[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [busy, setBusy] = useState('');
  const [result, setResult] = useState('');
  const [localError, setLocalError] = useState<SettingsErrorValue | null>(null);
  const [defaultsTab, setDefaultsTab] = useState<KnowledgeDefaultsTab>('overview');
  const [downloadType, setDownloadType] = useState<DownloadModelType>('embedding');
  const [downloadModelId, setDownloadModelId] = useState(KNOWLEDGE_MODEL_PRESETS[0].modelId);
  const [downloadTarget, setDownloadTarget] = useState(KNOWLEDGE_MODEL_PRESETS[0].target);
  const dirty = Boolean(values && settings && JSON.stringify(values) !== JSON.stringify(settings));
  const downloadCommand = `uv run python scripts/download_knowledge_model.py --type ${downloadType} --model-id ${downloadModelId || '<model-id>'} --target ${downloadTarget || '<target-folder>'}`;

  async function refresh() {
    const [nextSettings, nextProfiles, nextBases] = await Promise.all([
      api.getKnowledgeSettings(),
      api.listEmbeddingModels(),
      api.listKnowledgeBases(),
    ]);
    setSettings(nextSettings);
    setValues(nextSettings);
    setEmbeddingProfiles(nextProfiles);
    setKnowledgeBases(nextBases);
  }

  async function refreshObjects(selectedId?: string) {
    await refresh();
    await onObjectsChanged?.(selectedId);
  }

  useEffect(() => {
    void refresh()
      .then(() => api.scanKnowledgeModels())
      .then(setScan)
      .catch((error) => setLocalError(toSettingsError(error, 'Failed to load Knowledge settings.')));
  }, []);

  useEffect(() => {
    onDirtyChange(category === 'defaults' ? dirty : false);
  }, [category, dirty, onDirtyChange]);

  useEffect(() => {
    setBusy('');
    setResult('');
    setLocalError(null);
  }, [category, selectedItemId]);

  async function runScan() {
    setBusy('scan');
    try {
      setLocalError(null);
      setScan(await api.scanKnowledgeModels());
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to scan local models.'));
    } finally {
      setBusy('');
    }
  }

  async function switchLocalModelDevice(device: KnowledgeSettings['local_model_device']) {
    setBusy(`device:${device}`);
    try {
      setLocalError(null);
      const saved = await api.updateKnowledgeSettings({ local_model_device: device });
      setSettings(saved);
      setValues((current) => current ? { ...current, local_model_device: saved.local_model_device } : saved);
      setResult(t('knowledge:results.localModelDeviceSet', { device }));
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to update local model device.'));
    } finally {
      setBusy('');
    }
  }

  async function copyText(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setResult(t('knowledge:results.commandCopied'));
    } catch {
      setLocalError({ code: 'COPY_FAILED', message: t('knowledge:errors.copyCommandFailed'), details: {} });
    }
  }

  function selectPreset(index: number) {
    const preset = KNOWLEDGE_MODEL_PRESETS[index];
    setDownloadType(preset.type);
    setDownloadModelId(preset.modelId);
    setDownloadTarget(preset.target);
  }

  async function saveDefaults(event: FormEvent) {
    event.preventDefault();
    if (!values) return;
    setBusy('save');
    try {
      setLocalError(null);
      const saved = await api.updateKnowledgeSettings(knowledgeSettingsPatch(values));
      setSettings(saved);
      setValues(saved);
      setResult(t('knowledge:results.defaultsSaved'));
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to save Knowledge defaults.'));
    } finally {
      setBusy('');
    }
  }

  if (!values) {
    return <Empty title="Knowledge" message={t('knowledge:empty.loadingSettings')} />;
  }

  if (category === 'embedding_models') {
    return (
      <EmbeddingModelsEditor
        profiles={embeddingProfiles}
        scan={scan}
        mode={selectedItemId}
        onRefresh={refreshObjects}
        onDirtyChange={onDirtyChange}
      />
    );
  }

  if (category === 'knowledge_bases') {
    return (
      <KnowledgeBasesEditor
        knowledgeBases={knowledgeBases}
        profiles={embeddingProfiles}
        mode={selectedItemId}
        onRefresh={refreshObjects}
        onDirtyChange={onDirtyChange}
      />
    );
  }

  return (
    <form className="settings-detail-form" onSubmit={saveDefaults}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">
            <BrainCircuit size={18} />
          </div>
          <div>
            <h2>{t('knowledge:titles.defaults')}</h2>
            <p>{t('knowledge:descriptions.defaults')}</p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {result ? <span className="settings-badge success">{result}</span> : null}
          {dirty ? (
            <button className="settings-primary-button" type="submit" disabled={busy === 'save'}>
              <Save size={14} />
              {busy === 'save' ? t('common:saving') : t('common:save')}
            </button>
          ) : null}
        </div>
      </header>
      <DetailTabs
        tabs={[
          { id: 'overview', label: t('knowledge:tabs.overview') },
          { id: 'models', label: t('knowledge:tabs.models') },
          { id: 'retrieval', label: t('knowledge:tabs.retrieval') },
          { id: 'chunking', label: t('knowledge:tabs.chunking') },
          { id: 'context', label: t('knowledge:tabs.context') },
          { id: 'download', label: t('knowledge:tabs.download') },
        ]}
        activeTab={defaultsTab}
        onChange={(tab) => setDefaultsTab(tab as KnowledgeDefaultsTab)}
      />
      <div className="settings-detail-body">
        {localError ? <SettingsApiError error={localError} /> : null}
        {defaultsTab === 'overview' ? (
          <KnowledgeOverviewTab
            values={values}
            scan={scan}
            busy={busy}
            onRunScan={runScan}
            onSwitchDevice={switchLocalModelDevice}
            onSetValues={setValues}
            onCopy={copyText}
          />
        ) : null}
        {defaultsTab === 'models' ? <KnowledgeModelsTab values={values} setValues={setValues} scan={scan} busy={busy} setBusy={setBusy} setResult={setResult} setLocalError={setLocalError} /> : null}
        {defaultsTab === 'retrieval' ? <KnowledgeRetrievalTab values={values} setValues={setValues} /> : null}
        {defaultsTab === 'chunking' ? <KnowledgeChunkingTab values={values} setValues={setValues} /> : null}
        {defaultsTab === 'context' ? <KnowledgeContextTab values={values} setValues={setValues} /> : null}
        {defaultsTab === 'download' ? (
          <KnowledgeDownloadTab
            downloadType={downloadType}
            downloadModelId={downloadModelId}
            downloadTarget={downloadTarget}
            downloadCommand={downloadCommand}
            onSelectPreset={selectPreset}
            onSetType={setDownloadType}
            onSetModelId={setDownloadModelId}
            onSetTarget={setDownloadTarget}
            onCopy={copyText}
          />
        ) : null}
      </div>
    </form>
  );
}

function KnowledgeOverviewTab({
  values,
  scan,
  busy,
  onRunScan,
  onSwitchDevice,
  onSetValues,
  onCopy,
}: {
  values: KnowledgeSettings;
  scan: KnowledgeModelScan | null;
  busy: string;
  onRunScan: () => void;
  onSwitchDevice: (device: KnowledgeSettings['local_model_device']) => void;
  onSetValues: (values: KnowledgeSettings) => void;
  onCopy: (text: string) => void;
}) {
  const { t } = useTranslation(['knowledge', 'status']);
  const backend = scan?.backend;
  const missingOptionalDependencies = backend ? !backend.sentence_transformers_available || !backend.torch_available || !backend.transformers_available : false;
  const cudaMismatch = values.local_model_device === 'cuda' && backend?.cuda_available === false;
  return (
    <>
      <div className="detail-section">
        <div className="detail-section-heading">
          <h3>{t('knowledge:sections.localModels')}</h3>
        </div>
        <dl className="settings-definition-grid">
          <Metric label={t('knowledge:labels.modelsRoot')} value={values.models_root} />
          <Metric label={t('knowledge:labels.backend')} value={backendLabel(scan?.backend, t)} />
          <Metric label={t('knowledge:labels.embeddingFolders')} value={scan ? String(scan.embedding_models.length) : 'Not scanned'} />
          <Metric label={t('knowledge:labels.rerankerFolders')} value={scan ? String(scan.reranker_models.length) : 'Not scanned'} />
          <Metric label="sentence-transformers" value={dependencyLabel(backend?.sentence_transformers_available, t)} />
          <Metric label="torch" value={dependencyLabel(backend?.torch_available, t)} />
          <Metric label="transformers" value={dependencyLabel(backend?.transformers_available, t)} />
          <Metric label="CUDA" value={backend?.cuda_available ? 'yes' : backend ? 'no' : 'Not scanned'} />
          <Metric label={t('knowledge:labels.localModelDevice')} value={values.local_model_device} />
        </dl>
        <div className="settings-detail-grid">
          <SelectField label={t('knowledge:labels.localModelDevice')} value={values.local_model_device} options={['auto', 'cpu', 'cuda']} onChange={(value) => onSetValues({ ...values, local_model_device: value as KnowledgeSettings['local_model_device'] })} />
        </div>
        <div className="settings-button-row">
          <button className="settings-secondary-button" type="button" onClick={onRunScan} disabled={busy === 'scan'}>
            <RefreshCw size={14} />
            {busy === 'scan' ? t('knowledge:actions.scanning') : t('knowledge:actions.scanLocalModels')}
          </button>
        </div>
      </div>
      {cudaMismatch ? (
        <div className="detail-section knowledge-warning-section">
          <div className="detail-section-heading"><h3>{t('knowledge:install.cudaWarningTitle')}</h3></div>
          <p className="settings-warning-text">{t('knowledge:install.cudaWarningBody')}</p>
          <div className="settings-button-row">
            <button className="settings-secondary-button" type="button" onClick={() => onSwitchDevice('cpu')} disabled={Boolean(busy)}>
              {t('knowledge:actions.switchToCpu')}
            </button>
            <button className="settings-secondary-button" type="button" onClick={() => onSwitchDevice('auto')} disabled={Boolean(busy)}>
              {t('knowledge:actions.switchToAuto')}
            </button>
          </div>
        </div>
      ) : null}
      <div className="detail-section">
        <div className="detail-section-heading"><h3>{t('knowledge:install.title')}</h3></div>
        {missingOptionalDependencies ? <p className="settings-muted-text">{t('knowledge:install.missingOptionalDependencies')}</p> : null}
        {KNOWLEDGE_INSTALL_COMMANDS.map((item) => (
          <CommandCard
            key={item.key}
            title={t(`knowledge:install.commands.${item.key}`)}
            command={item.command}
            onCopy={onCopy}
          />
        ))}
        <p className="settings-muted-text">{t('knowledge:install.cudaDepends')}</p>
        <p className="settings-muted-text">{t('knowledge:install.pytorchSelector')}</p>
        <p className="settings-muted-text">{t('knowledge:install.restartAndScan')}</p>
        <p className="settings-muted-text">{t('knowledge:install.cudaUnavailableExplanation')}</p>
      </div>
    </>
  );
}

function KnowledgeModelsTab({
  values,
  setValues,
  scan,
  busy,
  setBusy,
  setResult,
  setLocalError,
}: {
  values: KnowledgeSettings;
  setValues: (values: KnowledgeSettings) => void;
  scan: KnowledgeModelScan | null;
  busy: string;
  setBusy: (busy: string) => void;
  setResult: (result: string) => void;
  setLocalError: (error: SettingsErrorValue | null) => void;
}) {
  const { t } = useTranslation(['knowledge']);
  const rerankerOptions = modelPathOptions(scan?.reranker_models ?? [], values.reranker_model_path || '');
  const currentRerankerMissing = scan ? Boolean(values.reranker_model_path) && !scan.reranker_models.some((model) => model.model_path === values.reranker_model_path) : false;
  return (
    <>
      <div className="detail-section">
        <div className="detail-section-heading"><h3>{t('knowledge:sections.embedding')}</h3></div>
        <div className="settings-detail-grid">
          <NumberField label={t('knowledge:labels.batchSize')} value={values.embedding_batch_size} onChange={(value) => { if (value !== '') setValues({ ...values, embedding_batch_size: value }); }} />
          <NumberField label={t('knowledge:labels.timeoutSeconds')} value={values.embedding_timeout_seconds} onChange={(value) => { if (value !== '') setValues({ ...values, embedding_timeout_seconds: value }); }} />
        </div>
        <label className="config-field settings-config-field boolean-field">
          <span>{t('knowledge:labels.unloadEmbeddingModelAfterUse')}</span>
          <ToggleSwitch checked={values.unload_embedding_model_after_use} onChange={(checked) => setValues({ ...values, unload_embedding_model_after_use: checked })} />
        </label>
        <p className="settings-muted-text">{t('knowledge:hints.unloadEmbeddingModelAfterUse')}</p>
      </div>
      <div className="detail-section">
        <div className="detail-section-heading"><h3>{t('knowledge:sections.reranker')}</h3></div>
        <label className="config-field settings-config-field boolean-field">
          <span>{t('knowledge:labels.enabled')}</span>
          <ToggleSwitch checked={values.reranker_enabled} onChange={(checked) => setValues({ ...values, reranker_enabled: checked })} />
        </label>
        <div className="settings-detail-grid">
          <div>
            <SelectField
              label={t('knowledge:labels.rerankerModelPath')}
              value={values.reranker_model_path || ''}
              options={rerankerOptions}
              labels={modelPathLabels(rerankerOptions)}
              disabled={!rerankerOptions.length}
              placeholder={t('knowledge:empty.noLocalRerankerModels')}
              onChange={(value) => setValues({ ...values, reranker_model_path: value || null })}
            />
            <p className="settings-muted-text">{t('knowledge:hints.chooseScannedRerankerModel')}</p>
            {!rerankerOptions.length ? <p className="settings-muted-text">{t('knowledge:hints.scanLocalModelsInOverviewFirst')}</p> : null}
            {currentRerankerMissing ? <p className="settings-muted-text">{t('knowledge:hints.currentSavedPathNotScanned')}</p> : null}
          </div>
          <NumberField label={t('knowledge:labels.batchSize')} value={values.reranker_batch_size} onChange={(value) => { if (value !== '') setValues({ ...values, reranker_batch_size: value }); }} />
          <NumberField label={t('knowledge:labels.timeoutSeconds')} value={values.reranker_timeout_seconds} onChange={(value) => { if (value !== '') setValues({ ...values, reranker_timeout_seconds: value }); }} />
          <NumberField label={t('knowledge:labels.candidateLimit')} value={values.reranker_candidate_limit} onChange={(value) => { if (value !== '') setValues({ ...values, reranker_candidate_limit: value }); }} />
        </div>
        <label className="config-field settings-config-field boolean-field">
          <span>{t('knowledge:labels.unloadRerankerModelAfterUse')}</span>
          <ToggleSwitch checked={values.unload_reranker_model_after_use} onChange={(checked) => setValues({ ...values, unload_reranker_model_after_use: checked })} />
        </label>
        <p className="settings-muted-text">{t('knowledge:hints.unloadRerankerModelAfterUse')}</p>
        <div className="settings-button-row">
          <button className="settings-secondary-button" type="button" onClick={async () => {
            setBusy('rerank');
            try {
              setLocalError(null);
              const response = await api.rerankKnowledge({ query: 'What is RAG?', documents: [{ id: 'doc1', text: 'Retrieval augmented generation uses retrieved context.' }, { id: 'doc2', text: 'Other text.' }] });
              setResult(t('knowledge:results.rerankerReturned', { count: response.results.length }));
            } catch (error) {
              setLocalError(toSettingsError(error, 'Reranker unavailable.'));
            } finally {
              setBusy('');
            }
          }} disabled={Boolean(busy)}>
            <Play size={14} />
            {t('knowledge:actions.testReranker')}
          </button>
        </div>
      </div>
    </>
  );
}

function KnowledgeRetrievalTab({ values, setValues }: { values: KnowledgeSettings; setValues: (values: KnowledgeSettings) => void }) {
  const { t } = useTranslation('knowledge');
  return (
    <>
      <NumberGroup title={t('sections.retrieval')} values={values} setValues={setValues} fields={[['default_vector_candidate_k', t('labels.vectorCandidateK')], ['default_keyword_candidate_k', t('labels.keywordCandidateK')], ['default_final_top_k', t('labels.finalTopK')], ['default_max_context_chars', t('labels.maxContextChars')], ['rrf_k', t('labels.rrfK')]]} />
      <div className="detail-section">
        <div className="detail-section-heading"><h3>{t('sections.retrievalSwitches')}</h3></div>
        <label className="config-field settings-config-field boolean-field">
          <span>{t('labels.enabled')}</span>
          <ToggleSwitch checked={values.hybrid_search_enabled} onChange={(checked) => setValues({ ...values, hybrid_search_enabled: checked })} />
        </label>
        <div className="settings-detail-grid">
          <NumberField label={t('labels.minScoreThreshold')} value={values.min_score_threshold ?? ''} onChange={(value) => setValues({ ...values, min_score_threshold: value === '' ? null : Number(value) })} />
          <NumberField label={t('labels.perSourceMaxChunks')} value={values.retrieval_max_chunks_per_source ?? ''} onChange={(value) => setValues({ ...values, retrieval_max_chunks_per_source: value === '' ? null : Number(value) })} />
          <NumberField label={t('labels.perKbMaxChunks')} value={values.retrieval_max_chunks_per_knowledge_base ?? ''} onChange={(value) => setValues({ ...values, retrieval_max_chunks_per_knowledge_base: value === '' ? null : Number(value) })} />
        </div>
      </div>
      <div className="detail-section">
        <div className="detail-section-heading"><h3>{t('sections.queryExpansion')}</h3></div>
        <label className="config-field settings-config-field boolean-field">
          <span>{t('labels.enabled')}</span>
          <ToggleSwitch checked={values.query_expansion_enabled} onChange={(checked) => setValues({ ...values, query_expansion_enabled: checked })} />
        </label>
        <div className="settings-detail-grid">
          <NumberField label={t('labels.maxVariants')} value={values.query_expansion_max_variants} onChange={(value) => { if (value !== '') setValues({ ...values, query_expansion_max_variants: value }); }} />
        </div>
        <TextAreaField label={t('labels.expansionPrompt')} value={values.query_expansion_prompt} onChange={(value) => setValues({ ...values, query_expansion_prompt: value })} />
      </div>
    </>
  );
}

function KnowledgeChunkingTab({ values, setValues }: { values: KnowledgeSettings; setValues: (values: KnowledgeSettings) => void }) {
  const { t } = useTranslation('knowledge');
  return (
    <>
      <div className="detail-section">
        <div className="detail-section-heading"><h3>{t('sections.chunking')}</h3></div>
        <div className="settings-detail-grid">
          <NumberField label={t('labels.chunkSize')} value={values.default_chunk_size} onChange={(value) => { if (value !== '') setValues({ ...values, default_chunk_size: value }); }} />
          <NumberField label={t('labels.chunkOverlap')} value={values.default_chunk_overlap} onChange={(value) => { if (value !== '') setValues({ ...values, default_chunk_overlap: value }); }} />
        </div>
      </div>
      <NumberGroup title={t('sections.indexLimits')} values={values} setValues={setValues} fields={[['max_source_size_bytes', t('labels.maxSourceSizeBytes')], ['max_chunks_per_source', t('labels.maxChunksPerSource')], ['max_total_index_chars_per_source', t('labels.maxTotalIndexCharsPerSource')]]} />
    </>
  );
}

function KnowledgeContextTab({ values, setValues }: { values: KnowledgeSettings; setValues: (values: KnowledgeSettings) => void }) {
  const { t } = useTranslation('knowledge');
  return (
    <div className="detail-section">
      <div className="detail-section-heading"><h3>{t('sections.contextInjection')}</h3></div>
      <TextAreaField label={t('labels.knowledgeContextInstruction')} value={values.knowledge_context_instruction} onChange={(value) => setValues({ ...values, knowledge_context_instruction: value })} />
      <TextAreaField label={t('labels.snippetTemplate')} value={values.knowledge_context_snippet_template} onChange={(value) => setValues({ ...values, knowledge_context_snippet_template: value })} />
    </div>
  );
}

function KnowledgeDownloadTab({
  downloadType,
  downloadModelId,
  downloadTarget,
  downloadCommand,
  onSelectPreset,
  onSetType,
  onSetModelId,
  onSetTarget,
  onCopy,
}: {
  downloadType: DownloadModelType;
  downloadModelId: string;
  downloadTarget: string;
  downloadCommand: string;
  onSelectPreset: (index: number) => void;
  onSetType: (type: DownloadModelType) => void;
  onSetModelId: (value: string) => void;
  onSetTarget: (value: string) => void;
  onCopy: (text: string) => void;
}) {
  const { t } = useTranslation('knowledge');
  return (
    <>
      <div className="detail-section">
        <div className="detail-section-heading"><h3>{t('download.modelPresets')}</h3></div>
        <p className="settings-muted-text">{t('download.vramEstimateDisclaimer')}</p>
        <p className="settings-muted-text">{t('download.cpuMemoryNote')}</p>
        {KNOWLEDGE_MODEL_PRESET_GROUPS.map((group) => (
          <div className="knowledge-model-preset-group" key={group}>
            <h4>{t(`download.groups.${group}`)}</h4>
            <div className="knowledge-model-preset-list">
              {KNOWLEDGE_MODEL_PRESETS.map((preset, index) => ({ preset, index }))
                .filter(({ preset }) => preset.group === group)
                .map(({ preset, index }) => (
                  <button className="knowledge-model-preset" type="button" key={preset.modelId} onClick={() => onSelectPreset(index)}>
                    <strong>{preset.modelId}</strong>
                    <span>{t(`download.modelTypes.${preset.type}`)} - {t(`download.notes.${preset.noteKey}`)}</span>
                    <span>{t('download.estimatedVram', { value: t(`download.estimatedVramValues.${preset.estimatedVramKey}`) })}</span>
                    <code>{preset.target}</code>
                  </button>
                ))}
            </div>
          </div>
        ))}
      </div>
      <div className="detail-section">
        <div className="detail-section-heading"><h3>{t('download.generatedCommand')}</h3></div>
        <p className="settings-muted-text">{t('download.runFromProjectRoot')}</p>
        <p className="settings-muted-text">{t('download.scanAfterDownload')}</p>
        <div className="settings-detail-grid">
          <SelectField label={t('download.modelType')} value={downloadType} options={['embedding', 'reranker']} labels={{ embedding: t('download.modelTypes.embedding'), reranker: t('download.modelTypes.reranker') }} onChange={(value) => onSetType(value as DownloadModelType)} />
          <TextField label={t('download.targetFolder')} value={downloadTarget} onChange={onSetTarget} />
        </div>
        <TextField label={t('download.customModelId')} value={downloadModelId} onChange={onSetModelId} />
        <CommandCard command={downloadCommand} onCopy={onCopy} />
      </div>
    </>
  );
}

function EmbeddingModelsEditor({ profiles, scan, mode, onRefresh, onDirtyChange }: {
  profiles: EmbeddingModelProfile[];
  scan: KnowledgeModelScan | null;
  mode: FormMode;
  onRefresh: (selectedItemId?: string) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation('knowledge');
  const selected = profiles.find((profile) => profile.id === mode);
  const initial = mode === 'new' ? defaultEmbeddingProfile : selected;
  if (!initial) {
    return <Empty title={t('empty.noEmbeddingSelected')} message={profiles.length ? t('empty.selectEmbedding') : t('empty.noEmbeddingProfiles')} />;
  }
  return <EmbeddingProfileForm initial={initial} scan={scan} isNew={mode === 'new'} onRefresh={onRefresh} onDirtyChange={onDirtyChange} />;
}

function EmbeddingProfileForm({ initial, scan, isNew, onRefresh, onDirtyChange }: {
  initial: Partial<EmbeddingModelProfile>;
  scan: KnowledgeModelScan | null;
  isNew: boolean;
  onRefresh: (selectedItemId?: string) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation(['knowledge', 'common']);
  const [values, setValues] = useState<Partial<EmbeddingModelProfile>>(initial);
  const [busy, setBusy] = useState('');
  const [result, setResult] = useState('');
  const [error, setError] = useState<SettingsErrorValue | null>(null);
  const [normalizeTouched, setNormalizeTouched] = useState(false);
  const scopeId = isNew ? 'new' : initial.id || '';
  const dirty = stableConfigString(buildEmbeddingModelPayload(values)) !== stableConfigString(buildEmbeddingModelPayload(initial));
  const embeddingOptions = modelPathOptions(scan?.embedding_models ?? [], values.model_path || '');
  const currentEmbeddingMissing = scan ? Boolean(values.model_path) && !scan.embedding_models.some((model) => model.model_path === values.model_path) : false;

  useEffect(() => {
    setValues(initial);
    setNormalizeTouched(false);
  }, [initial]);

  useEffect(() => {
    setBusy('');
    setResult('');
    setError(null);
  }, [scopeId]);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy('saving');
    try {
      setError(null);
      const payload = buildEmbeddingModelPayload(values);
      const saved = isNew ? await api.createEmbeddingModel(payload) : await api.patchEmbeddingModel(values.id || '', payload);
      await onRefresh(saved.id);
      setResult(t('knowledge:results.embeddingSaved'));
    } catch (error) {
      setError(toSettingsError(error, 'Failed to save embedding model.'));
    } finally {
      setBusy('');
    }
  }
  async function remove() {
    if (!values.id) return;
    setBusy('deleting');
    try {
      setError(null);
      await api.deleteEmbeddingModel(values.id);
      await onRefresh();
      setResult(t('knowledge:results.embeddingDeleted'));
    } catch (error) {
      setError(toSettingsError(error, 'Failed to delete embedding model.'));
    } finally {
      setBusy('');
    }
  }
  async function test() {
    if (!values.id) return;
    setBusy('testing');
    try {
      setError(null);
      const response = await api.testEmbeddingModel(values.id, 'hello world', 'query');
      setResult(t('knowledge:results.embeddingDimension', { dimension: response.dimension }));
    } catch (error) {
      setError(toSettingsError(error, 'Embedding backend unavailable.'));
    } finally {
      setBusy('');
    }
  }
  function selectModelPath(modelPath: string) {
    const preset = embeddingPresetForPath(modelPath);
    const folderName = modelFolderName(modelPath);
    const fallback: EmbeddingProfilePreset = {
      name: folderName,
      alias: safeProfileKey(folderName),
      normalize: values.normalize ?? true,
    };
    const profile = preset?.profile ?? fallback;
    setValues({
      ...values,
      model_path: modelPath,
      name: values.name?.trim() ? values.name : profile.name,
      alias: values.alias?.trim() ? values.alias : profile.alias,
      dimension: values.dimension || values.dimension === 0 ? values.dimension : (profile.dimension ?? null),
      normalize: normalizeTouched ? (values.normalize ?? true) : profile.normalize,
      document_instruction: values.document_instruction?.trim() ? values.document_instruction : (profile.document_instruction ?? ''),
      query_instruction: values.query_instruction?.trim() ? values.query_instruction : (profile.query_instruction ?? ''),
    });
    if (preset) {
      setResult(t('knowledge:results.recommendedPresetApplied'));
    }
  }
  return (
    <form className="settings-detail-form" onSubmit={save}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">{profileInitials(values.name || values.alias || 'EM') || <BrainCircuit size={18} />}</div>
          <div>
            <h2>{values.name || t('knowledge:titles.newEmbeddingModel')}</h2>
            <p>
              <code>{values.alias || 'profile_key'}</code>
              <span>{values.model_path || t('knowledge:empty.noModelPath')}</span>
            </p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {result ? <span className="settings-badge success">{result}</span> : null}
          {dirty ? (
            <button className="settings-primary-button" type="submit" disabled={Boolean(busy)}>
              <Save size={14} />
              {busy === 'saving' ? t('common:saving') : t('common:save')}
            </button>
          ) : null}
          {!isNew ? <button className="settings-secondary-button" type="button" onClick={test} disabled={Boolean(busy)}><Play size={14} />{busy === 'testing' ? t('knowledge:actions.testing') : t('knowledge:actions.test')}</button> : null}
          {!isNew ? <button className="settings-secondary-button danger" type="button" onClick={remove} disabled={Boolean(busy)}><Trash2 size={14} />{t('common:delete')}</button> : null}
          <ToggleSwitch checked={values.enabled ?? true} onChange={(checked) => setValues({ ...values, enabled: checked })} disabled={Boolean(busy)} />
        </div>
      </header>
      <div className="settings-detail-body">
        {error ? <SettingsApiError error={error} /> : null}
        <section className="detail-section">
          <h3>{t('knowledge:sections.model')}</h3>
          <div className="settings-detail-grid">
            <TextField label={t('knowledge:labels.name')} value={values.name || ''} onChange={(value) => setValues({ ...values, name: value })} />
            <TextField label={t('knowledge:labels.profileKey')} value={values.alias || ''} onChange={(value) => setValues({ ...values, alias: value })} />
            <div>
              <SelectField
                label={t('knowledge:labels.modelPathChooseFirst')}
                value={values.model_path || ''}
                options={embeddingOptions}
                labels={modelPathLabels(embeddingOptions)}
                disabled={!embeddingOptions.length}
                placeholder={t('knowledge:empty.noLocalEmbeddingModels')}
                onChange={selectModelPath}
              />
              <p className="settings-muted-text">{t('knowledge:hints.chooseScannedEmbeddingModel')}</p>
              <p className="settings-muted-text">{t('knowledge:hints.presetFieldsFilledWhenAvailable')}</p>
              {!embeddingOptions.length ? <p className="settings-muted-text">{t('knowledge:hints.scanLocalModelsInOverviewFirst')}</p> : null}
              {currentEmbeddingMissing ? <p className="settings-muted-text">{t('knowledge:hints.currentSavedPathNotScanned')}</p> : null}
            </div>
            <NumberField label={t('knowledge:labels.dimension')} value={values.dimension ?? ''} onChange={(value) => setValues({ ...values, dimension: value === '' ? null : Number(value) })} />
          </div>
        </section>
        <section className="detail-section">
          <h3>{t('knowledge:sections.runtime')}</h3>
          <label className="config-field settings-config-field boolean-field"><span>{t('knowledge:labels.normalize')}</span><ToggleSwitch checked={values.normalize ?? true} onChange={(checked) => { setNormalizeTouched(true); setValues({ ...values, normalize: checked }); }} /></label>
          <TextAreaField label={t('knowledge:labels.documentInstruction')} value={values.document_instruction || ''} onChange={(value) => setValues({ ...values, document_instruction: value })} />
          <TextAreaField label={t('knowledge:labels.queryInstruction')} value={values.query_instruction || ''} onChange={(value) => setValues({ ...values, query_instruction: value })} />
          <TextAreaField label={t('knowledge:labels.notes')} value={values.notes || ''} onChange={(value) => setValues({ ...values, notes: value })} />
        </section>
      </div>
    </form>
  );
}

function KnowledgeBasesEditor({ knowledgeBases, profiles, mode, onRefresh, onDirtyChange }: {
  knowledgeBases: KnowledgeBase[];
  profiles: EmbeddingModelProfile[];
  mode: FormMode;
  onRefresh: (selectedItemId?: string) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation('knowledge');
  const selected = knowledgeBases.find((kb) => kb.id === mode);
  const initial = useMemo(() => mode === 'new' ? { ...defaultKnowledgeBase, embedding_model_profile_id: profiles[0]?.id || '' } : selected, [mode, profiles, selected]);
  if (!initial) {
    return <Empty title={t('empty.noKnowledgeBaseSelected')} message={knowledgeBases.length ? t('empty.selectKnowledgeBase') : t('empty.noKnowledgeBases')} />;
  }
  return <KnowledgeBaseForm initial={initial} profiles={profiles} isNew={mode === 'new'} onRefresh={onRefresh} onDirtyChange={onDirtyChange} />;
}

function KnowledgeBaseForm({ initial, profiles, isNew, onRefresh, onDirtyChange }: {
  initial: Partial<KnowledgeBase>;
  profiles: EmbeddingModelProfile[];
  isNew: boolean;
  onRefresh: (selectedItemId?: string) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation(['knowledge', 'common', 'status']);
  const [values, setValues] = useState<Partial<KnowledgeBase>>(initial);
  const [busy, setBusy] = useState('');
  const [configResult, setConfigResult] = useState('');
  const [configError, setConfigError] = useState<SettingsErrorValue | null>(null);
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [origins, setOrigins] = useState<KnowledgeOrigin[]>([]);
  const [originName, setOriginName] = useState('');
  const [originSlug, setOriginSlug] = useState('');
  const [originDefaultChunkProfile, setOriginDefaultChunkProfile] = useState('');
  const [originIndexAfterCreate, setOriginIndexAfterCreate] = useState(false);
  const [originFolderSuggestions, setOriginFolderSuggestions] = useState<KnowledgeOriginFolderSuggestion[]>([]);
  const [originFolderSuggestionsLoading, setOriginFolderSuggestionsLoading] = useState(false);
  const [originFolderSuggestionsOpen, setOriginFolderSuggestionsOpen] = useState(false);
  const [originFolderSuggestionActiveIndex, setOriginFolderSuggestionActiveIndex] = useState(0);
  const [originFolderSuggestionError, setOriginFolderSuggestionError] = useState(false);
  const [originFolderPopupRect, setOriginFolderPopupRect] = useState<{ left: number; top: number; width: number } | null>(null);
  const [sourceResult, setSourceResult] = useState('');
  const [sourceTitle, setSourceTitle] = useState('');
  const [sourceText, setSourceText] = useState('');
  const [sourceFolderPath, setSourceFolderPath] = useState('');
  const [sourceChunkProfile, setSourceChunkProfile] = useState('');
  const [importFiles, setImportFiles] = useState<File[]>([]);
  const [importDragActive, setImportDragActive] = useState(false);
  const [sourceError, setSourceError] = useState<SettingsErrorValue | null>(null);
  const [modalError, setModalError] = useState<SettingsErrorValue | null>(null);
  const [sourceSort, setSourceSort] = useState<{ key: SourceSortKey; direction: SortDirection }>({ key: 'indexed_at', direction: 'desc' });
  const [selectedSourceId, setSelectedSourceId] = useState('');
  const [sourcePreview, setSourcePreview] = useState<KnowledgeSourcePreview | null>(null);
  const [sourceChunks, setSourceChunks] = useState<KnowledgeSourceChunk[]>([]);
  const [sourceDetailError, setSourceDetailError] = useState<SettingsErrorValue | null>(null);
  const [sourceDetailLoading, setSourceDetailLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResponse, setSearchResponse] = useState<KnowledgeSearchResponse | null>(null);
  const [searchError, setSearchError] = useState<SettingsErrorValue | null>(null);
  const [activeTab, setActiveTab] = useState<KnowledgeBaseTab>('config');
  const [sourceModal, setSourceModal] = useState<SourceModal>(null);
  const [expandedOriginIds, setExpandedOriginIds] = useState<Set<string>>(() => new Set());
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const originFolderInputRef = useRef<HTMLDivElement | null>(null);
  const searchRequestRef = useRef(0);
  const originFolderRequestRef = useRef(0);
  const originFolderLastRequestRef = useRef('');
  const originFolderSuggestionCacheRef = useRef<Map<string, KnowledgeOriginFolderSuggestion[]>>(new Map());
  const currentKnowledgeBaseIdRef = useRef(initial.id || '');
  currentKnowledgeBaseIdRef.current = initial.id || '';
  const scopeId = isNew ? 'new' : initial.id || '';
  const selectedProfile = profiles.find((profile) => profile.id === values.embedding_model_profile_id);
  const selectedProfileName = values.embedding_model_profile_name || selectedProfile?.name || '';
  const sortedSources = useMemo(() => sortSources(sources, sourceSort), [sourceSort, sources]);
  const selectedSource = sources.find((source) => source.id === selectedSourceId) || null;
  const hasStaleOriginSources = sources.some((source) => ['new', 'changed'].includes(source.file_status || '') || source.status === 'needs_reindex');
  const dirty = stableConfigString(buildKnowledgeBasePayload(values)) !== stableConfigString(buildKnowledgeBasePayload(initial));
  const originFolderParent = originFolderParentPrefix(originSlug);
  const originFolderSearch = originFolderSearchTerm(originSlug);
  const visibleOriginFolderSuggestions = useMemo(() => {
    const query = originFolderSearch.toLowerCase();
    return originFolderSuggestions.filter((folder) => {
      if (!query) return true;
      return folder.name.toLowerCase().includes(query) || originFolderLeafName(folder.path).toLowerCase().includes(query);
    });
  }, [originFolderSearch, originFolderSuggestions]);
  const showOriginFolderSuggestions = sourceModal === 'create_origin'
    && originFolderSuggestionsOpen
    && (visibleOriginFolderSuggestions.length > 0 || originFolderSuggestionsLoading);

  const updateOriginFolderPopupRect = useCallback(() => {
    const element = originFolderInputRef.current;
    if (!element) {
      setOriginFolderPopupRect(null);
      return;
    }
    const rect = element.getBoundingClientRect();
    setOriginFolderPopupRect({ left: rect.left, top: rect.bottom + 6, width: rect.width });
  }, []);

  useEffect(() => {
    setValues(initial);
  }, [initial]);

  useEffect(() => {
    setBusy('');
    setConfigResult('');
    setConfigError(null);
    currentKnowledgeBaseIdRef.current = initial.id || '';
  }, [scopeId]);

  useEffect(() => {
    setActiveTab('config');
    setSearchQuery('');
    setSearchResponse(null);
    setSearchError(null);
    setSourceError(null);
    setSourceResult('');
    setSourceTitle('');
    setSourceText('');
    setSourceFolderPath('');
    setSourceChunkProfile('');
    setImportFiles([]);
    setSourceModal(null);
    setOriginName('');
    setOriginSlug('');
    setOriginDefaultChunkProfile('');
    setOriginIndexAfterCreate(false);
    setOriginFolderSuggestions([]);
    setOriginFolderSuggestionsOpen(false);
    setOriginFolderSuggestionActiveIndex(0);
    setOriginFolderSuggestionError(false);
    setModalError(null);
    setImportDragActive(false);
    setOrigins([]);
    setExpandedOriginIds(new Set());
    setSelectedSourceId('');
    setSourcePreview(null);
    setSourceChunks([]);
    setSourceDetailError(null);
    searchRequestRef.current += 1;
    currentKnowledgeBaseIdRef.current = initial.id || '';
  }, [initial.id, isNew]);

  useEffect(() => {
    if (activeTab === 'config') {
      setSourceError(null);
      setSourceResult('');
      setSearchError(null);
    } else {
      setConfigError(null);
      setConfigResult('');
    }
  }, [activeTab]);

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(() => {
    if (!initial.id || isNew) {
      setSources([]);
      setOrigins([]);
      return;
    }
    void loadKnowledgeLists(initial.id);
  }, [initial.id, isNew]);

  useEffect(() => {
    if (activeTab !== 'config' && values.id && !isNew) {
      void loadKnowledgeLists(values.id);
    }
  }, [activeTab, values.id, isNew]);

  useEffect(() => {
    if (sourceModal !== 'create_origin') {
      setOriginFolderSuggestions([]);
      setOriginFolderSuggestionsLoading(false);
      setOriginFolderSuggestionError(false);
      setOriginFolderPopupRect(null);
      originFolderRequestRef.current += 1;
      return;
    }
    const parent = originFolderParent;
    const cached = originFolderSuggestionCacheRef.current.get(parent);
    if (cached) {
      setOriginFolderSuggestions(cached);
      setOriginFolderSuggestionsLoading(false);
      setOriginFolderSuggestionError(false);
      originFolderLastRequestRef.current = parent;
      return;
    }
    if (originFolderLastRequestRef.current === parent && originFolderSuggestions.length) {
      return;
    }
    const requestId = originFolderRequestRef.current + 1;
    originFolderRequestRef.current = requestId;
    const timer = window.setTimeout(() => {
      originFolderLastRequestRef.current = parent;
      setOriginFolderSuggestionsLoading(true);
      setOriginFolderSuggestionError(false);
      api.listKnowledgeOriginFolders(parent)
        .then((response) => {
          if (originFolderRequestRef.current !== requestId) return;
          originFolderSuggestionCacheRef.current.set(parent, response.folders);
          setOriginFolderSuggestions(response.folders);
        })
        .catch(() => {
          if (originFolderRequestRef.current !== requestId) return;
          setOriginFolderSuggestionError(true);
          setOriginFolderSuggestions([]);
        })
        .finally(() => {
          if (originFolderRequestRef.current === requestId) setOriginFolderSuggestionsLoading(false);
        });
    }, 200);
    return () => {
      originFolderRequestRef.current += 1;
      window.clearTimeout(timer);
    };
  }, [originFolderParent, sourceModal]);

  useEffect(() => {
    setOriginFolderSuggestionActiveIndex(0);
  }, [originFolderSearch, originFolderSuggestions]);

  useEffect(() => {
    if (!showOriginFolderSuggestions) {
      setOriginFolderPopupRect(null);
      return;
    }
    updateOriginFolderPopupRect();
    window.addEventListener('resize', updateOriginFolderPopupRect);
    window.addEventListener('scroll', updateOriginFolderPopupRect, true);
    return () => {
      window.removeEventListener('resize', updateOriginFolderPopupRect);
      window.removeEventListener('scroll', updateOriginFolderPopupRect, true);
    };
  }, [showOriginFolderSuggestions, updateOriginFolderPopupRect, originSlug, visibleOriginFolderSuggestions.length]);

  async function loadKnowledgeLists(knowledgeBaseId = values.id || '') {
    if (!knowledgeBaseId) return;
    await Promise.all([loadSources(knowledgeBaseId), loadOrigins(knowledgeBaseId)]);
  }

  async function loadSources(knowledgeBaseId = values.id || '') {
    if (!knowledgeBaseId) return;
    try {
      const loadedSources = await api.listKnowledgeSources(knowledgeBaseId);
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) {
        setSources(loadedSources);
        setSelectedSourceId((current) => current && loadedSources.some((source) => source.id === current) ? current : '');
      }
    } catch (error) {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) {
        setSourceError(toSettingsError(error, 'Failed to load knowledge sources.'));
      }
    }
  }

  async function loadOrigins(knowledgeBaseId = values.id || '') {
    if (!knowledgeBaseId) return;
    try {
      const loadedOrigins = await api.listKnowledgeOrigins(knowledgeBaseId);
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) {
        setOrigins(loadedOrigins);
      }
    } catch (error) {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) {
        setSourceError(toSettingsError(error, 'Failed to load knowledge origins.'));
      }
    }
  }

  async function loadSourceDetail(sourceId: string) {
    if (!sourceId) return;
    const knowledgeBaseId = values.id || '';
    setSourceDetailLoading(true);
    try {
      setSourceDetailError(null);
      const [preview, chunks] = await Promise.all([
        api.getKnowledgeSourcePreview(sourceId),
        api.listKnowledgeSourceChunks(sourceId),
      ]);
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId && selectedSourceId === sourceId) {
        setSourcePreview(preview);
        setSourceChunks(chunks.chunks);
      }
    } catch (error) {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId && selectedSourceId === sourceId) {
        setSourcePreview(null);
        setSourceChunks([]);
        setSourceDetailError(toSettingsError(error, 'Failed to load source detail.'));
      }
    } finally {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId && selectedSourceId === sourceId) {
        setSourceDetailLoading(false);
      }
    }
  }

  useEffect(() => {
    if (!selectedSourceId) {
      setSourcePreview(null);
      setSourceChunks([]);
      setSourceDetailError(null);
      setSourceDetailLoading(false);
      return;
    }
    void loadSourceDetail(selectedSourceId);
  }, [selectedSourceId]);

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy('saving');
    try {
      setConfigError(null);
      const payload = buildKnowledgeBasePayload(values);
      const saved = isNew ? await api.createKnowledgeBase(payload) : await api.patchKnowledgeBase(values.id || '', payload);
      await onRefresh(saved.id);
      if (!isNew) await loadKnowledgeLists(saved.id);
      setConfigResult(t('knowledge:results.knowledgeBaseSaved'));
    } catch (error) {
      setConfigError(toSettingsError(error, 'Failed to save knowledge base.'));
    } finally {
      setBusy('');
    }
  }
  async function remove() {
    if (!values.id) return;
    setBusy('deleting');
    try {
      setConfigError(null);
      await api.deleteKnowledgeBase(values.id);
      await onRefresh();
      setConfigResult(t('knowledge:results.knowledgeBaseDeleted'));
    } catch (error) {
      setConfigError(toSettingsError(error, 'Failed to delete knowledge base.'));
    } finally {
      setBusy('');
    }
  }
  async function createOrigin(indexAfter = false) {
    if (!values.id || !originName.trim() || !originSlug.trim()) return;
    const knowledgeBaseId = values.id;
    setBusy('creating origin');
    try {
      setModalError(null);
      setSourceResult('');
      const created = await api.createKnowledgeOrigin(knowledgeBaseId, {
        name: originName,
        slug: originSlug,
        default_chunk_profile: originDefaultChunkProfile ? originDefaultChunkProfile as ChunkProfile : null,
      });
      if (currentKnowledgeBaseIdRef.current !== knowledgeBaseId) return;
      if (indexAfter) {
        await api.scanKnowledgeOrigin(created.id);
        await api.importKnowledgeOrigin(created.id);
      }
      setOriginName('');
      setOriginSlug('');
      setOriginDefaultChunkProfile('');
      setOriginIndexAfterCreate(false);
      setOriginFolderSuggestions([]);
      setOriginFolderSuggestionsOpen(false);
      setOriginFolderPopupRect(null);
      setOriginFolderSuggestionActiveIndex(0);
      setOriginFolderSuggestionError(false);
      setSourceModal(null);
      await loadKnowledgeLists(knowledgeBaseId);
      await onRefresh(knowledgeBaseId);
      setSourceResult(t('knowledge:results.originCreated', { path: created.root_path }));
    } catch (error) {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) {
        const nextError = toSettingsError(error, t('knowledge:errors.createOriginFailed'));
        setModalError(nextError.code === 'KNOWLEDGE_ORIGIN_SLUG_EXISTS'
          ? { ...nextError, message: t('knowledge:errors.originFolderAlreadyRegistered') }
          : nextError);
      }
    } finally {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) setBusy('');
    }
  }
  async function scanOrigin(originId: string) {
    if (!values.id) return;
    const knowledgeBaseId = values.id;
    setBusy(`scan origin:${originId}`);
    try {
      setSourceError(null);
      setSourceResult('');
      const summary = await api.scanKnowledgeOrigin(originId);
      if (currentKnowledgeBaseIdRef.current !== knowledgeBaseId) return;
      await loadKnowledgeLists(knowledgeBaseId);
      setSourceResult(t('knowledge:results.originScanned', summary));
    } catch (error) {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) {
        setSourceError(toSettingsError(error, 'Failed to scan knowledge origin.'));
      }
    } finally {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) setBusy('');
    }
  }
  async function importOrigin(originId: string, sourceIds?: string[], actionLabel = 'import origin') {
    if (!values.id) return;
    const knowledgeBaseId = values.id;
    setBusy(`${actionLabel}:${originId}`);
    try {
      setSourceError(null);
      setSourceResult('');
      const summary = await api.importKnowledgeOrigin(originId, sourceIds);
      if (currentKnowledgeBaseIdRef.current !== knowledgeBaseId) return;
      await loadKnowledgeLists(knowledgeBaseId);
      await onRefresh(knowledgeBaseId);
      setSourceResult(t('knowledge:results.originImported', summary));
    } catch (error) {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) {
        setSourceError(toSettingsError(error, 'Failed to import knowledge origin.'));
      }
    } finally {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) setBusy('');
    }
  }
  async function addPastedSource() {
    if (!values.id || !sourceTitle.trim() || !sourceText.trim()) return;
    const knowledgeBaseId = values.id;
    setBusy('indexing');
    try {
      setModalError(null);
      setSourceResult('');
      const indexed = await api.createPastedKnowledgeSource(knowledgeBaseId, {
        title: sourceTitle,
        text: sourceText,
        folder_path: sourceFolderPath,
        chunk_profile: sourceChunkProfile || null,
      });
      if (currentKnowledgeBaseIdRef.current !== knowledgeBaseId) return;
      setSourceTitle('');
      setSourceText('');
      setSourceFolderPath('');
      setSourceChunkProfile('');
      setSourceModal(null);
      setSelectedSourceId(indexed.source_id);
      await loadSources(knowledgeBaseId);
      await onRefresh(knowledgeBaseId);
      setSourceResult(t('knowledge:results.indexedChunks', { count: indexed.chunks }));
    } catch (error) {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) {
        setModalError(toSettingsError(error, t('knowledge:errors.indexPastedTextFailed')));
      }
    } finally {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) setBusy('');
    }
  }
  async function addFiles(files: FileList | File[], options: { folderPath?: string; chunkProfile?: string | null } = {}) {
    if (!values.id) return;
    const knowledgeBaseId = values.id;
    const accepted = Array.from(files).filter(isSupportedTextFile);
    const rejected = Array.from(files).filter((file) => !isSupportedTextFile(file));
    if (rejected.length) {
      setModalError({ code: 'UNSUPPORTED_FILE_TYPE', message: t('knowledge:errors.unsupportedFileType', { name: rejected[0].name || rejected[0].type || t('knowledge:labels.fileName') }) });
      if (!accepted.length) return;
    }
    setBusy('indexing file');
    try {
      setModalError(null);
      setSourceResult('');
      let indexedCount = 0;
      for (const file of accepted) {
        const attachment = await api.uploadAttachment(file);
        const attachmentId = (attachment.uri || '').replace(/^local:\/\/attachments\//, '');
        if (!attachmentId) throw new Error('Uploaded attachment did not return a local attachment id.');
        const indexed = await api.createAttachmentKnowledgeSource(knowledgeBaseId, {
          attachment_id: attachmentId,
          title: file.name || t('knowledge:defaults.attachmentTextTitle'),
          folder_path: options.folderPath || '',
          chunk_profile: options.chunkProfile || null,
        });
        indexedCount += indexed.chunks;
      }
      if (currentKnowledgeBaseIdRef.current !== knowledgeBaseId) return;
      await loadSources(knowledgeBaseId);
      await onRefresh(knowledgeBaseId);
      setImportFiles([]);
      setSourceFolderPath('');
      setSourceChunkProfile('');
      setSourceModal(null);
      setSourceResult(t('knowledge:results.indexedFiles', { chunks: indexedCount, files: accepted.length, count: accepted.length }));
    } catch (error) {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) {
        setModalError(toSettingsError(error, t('knowledge:errors.indexFilesFailed')));
      }
    } finally {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) setBusy('');
    }
  }
  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const files = event.currentTarget.files;
    if (files) addImportFiles(Array.from(files));
    event.currentTarget.value = '';
  }
  const openSourceModal = useCallback((modal: SourceModal) => {
    setModalError(null);
    setImportDragActive(false);
    setSourceModal(modal);
  }, []);
  const closeSourceModal = useCallback(() => {
    if (sourceModal === 'create_origin') {
      setOriginName('');
      setOriginSlug('');
      setOriginDefaultChunkProfile('');
      setOriginIndexAfterCreate(false);
      setOriginFolderSuggestions([]);
      setOriginFolderSuggestionsOpen(false);
      setOriginFolderSuggestionActiveIndex(0);
      setOriginFolderSuggestionError(false);
    }
    if (sourceModal === 'import_files') {
      setImportFiles([]);
      setSourceFolderPath('');
      setSourceChunkProfile('');
    }
    if (sourceModal === 'paste_text') {
      setSourceTitle('');
      setSourceText('');
      setSourceFolderPath('');
      setSourceChunkProfile('');
    }
    setSourceModal(null);
    setModalError(null);
    setImportDragActive(false);
  }, [sourceModal]);
  function selectOriginFolderSuggestion(path: string) {
    setOriginSlug(path);
    setOriginFolderSuggestionsOpen(false);
    setOriginFolderPopupRect(null);
  }
  function onOriginFolderKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (!showOriginFolderSuggestions) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setOriginFolderSuggestionActiveIndex((current) => Math.min(current + 1, Math.max(visibleOriginFolderSuggestions.length - 1, 0)));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setOriginFolderSuggestionActiveIndex((current) => Math.max(current - 1, 0));
    } else if (event.key === 'Enter' && visibleOriginFolderSuggestions[originFolderSuggestionActiveIndex]) {
      event.preventDefault();
      selectOriginFolderSuggestion(visibleOriginFolderSuggestions[originFolderSuggestionActiveIndex].path);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      setOriginFolderSuggestionsOpen(false);
    }
  }
  function addImportFiles(files: File[]) {
    const next = [...importFiles];
    let duplicateCount = 0;
    for (const file of files.filter(isSupportedTextFile)) {
      const duplicate = next.some((item) => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified);
      if (duplicate) {
        duplicateCount += 1;
        continue;
      }
      next.push(file);
    }
    const unsupported = files.find((file) => !isSupportedTextFile(file));
    setImportFiles(next);
    if (unsupported) {
      setModalError({ code: 'UNSUPPORTED_FILE_TYPE', message: t('knowledge:errors.unsupportedFileType', { name: unsupported.name || unsupported.type || t('knowledge:labels.fileName') }) });
    } else if (duplicateCount) {
      setModalError({ code: 'DUPLICATE_FILE_SKIPPED', message: t('knowledge:errors.duplicateFilesSkipped', { count: duplicateCount }) });
    } else {
      setModalError(null);
    }
  }
  function removeImportFile(index: number) {
    setImportFiles((current) => current.filter((_, itemIndex) => itemIndex !== index));
  }
  function onImportDragOver(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault();
    setImportDragActive(true);
  }
  function onImportDragLeave(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault();
    setImportDragActive(false);
  }
  function onImportDrop(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault();
    setImportDragActive(false);
    addImportFiles(Array.from(event.dataTransfer.files));
  }
  async function deleteOrigin(origin: KnowledgeOrigin) {
    if (!values.id) return;
    const confirmed = window.confirm(t('knowledge:confirm.deleteOrigin', { name: origin.name }));
    if (!confirmed) return;
    const knowledgeBaseId = values.id;
    setBusy(`delete origin:${origin.id}`);
    try {
      setSourceError(null);
      setSourceResult('');
      await api.deleteKnowledgeOrigin(origin.id);
      if (currentKnowledgeBaseIdRef.current !== knowledgeBaseId) return;
      setExpandedOriginIds((current) => {
        const next = new Set(current);
        next.delete(origin.id);
        return next;
      });
      setSelectedSourceId((current) => sources.some((source) => source.origin_id === origin.id && source.id === current) ? '' : current);
      await loadKnowledgeLists(knowledgeBaseId);
      await onRefresh(knowledgeBaseId);
      setSourceResult(t('knowledge:results.originDeleted'));
    } catch (error) {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) {
        setSourceError(toSettingsError(error, t('knowledge:errors.deleteOriginFailed')));
      }
    } finally {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) setBusy('');
    }
  }
  function toggleSourceSort(key: SourceSortKey) {
    setSourceSort((current) => ({
      key,
      direction: current.key === key && current.direction === 'asc' ? 'desc' : 'asc',
    }));
  }
  async function deleteSource(sourceId: string) {
    if (!values.id) return;
    const knowledgeBaseId = values.id;
    setBusy('deleting source');
    try {
      setSourceError(null);
      setSourceResult('');
      await api.deleteKnowledgeSource(sourceId);
      if (currentKnowledgeBaseIdRef.current !== knowledgeBaseId) return;
      if (selectedSourceId === sourceId) {
        setSelectedSourceId('');
        setSourcePreview(null);
        setSourceChunks([]);
      }
      await loadSources(knowledgeBaseId);
      await onRefresh(knowledgeBaseId);
      setSourceResult(t('knowledge:results.sourceDeleted'));
    } catch (error) {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) {
        setSourceError(toSettingsError(error, 'Failed to delete source.'));
      }
    } finally {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) setBusy('');
    }
  }
  async function reindexSource(sourceId: string) {
    if (!values.id) return;
    const knowledgeBaseId = values.id;
    setBusy('reindexing');
    try {
      setSourceError(null);
      setSourceResult('');
      const result = await api.reindexKnowledgeSource(sourceId);
      if (currentKnowledgeBaseIdRef.current !== knowledgeBaseId) return;
      await loadSources(knowledgeBaseId);
      if (selectedSourceId === sourceId) await loadSourceDetail(sourceId);
      await onRefresh(knowledgeBaseId);
      setSourceResult(t('knowledge:results.reindexedChunks', { count: result.chunks }));
    } catch (error) {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) {
        setSourceError(toSettingsError(error, 'Failed to reindex source.'));
      }
    } finally {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) setBusy('');
    }
  }
  async function reindexAllSources() {
    if (!values.id) return;
    const knowledgeBaseId = values.id;
    setBusy('reindexing all');
    try {
      setSourceError(null);
      setSourceResult('');
      const result = await api.reindexKnowledgeBase(knowledgeBaseId);
      if (currentKnowledgeBaseIdRef.current !== knowledgeBaseId) return;
      await loadSources(knowledgeBaseId);
      if (selectedSourceId) await loadSourceDetail(selectedSourceId);
      await onRefresh(knowledgeBaseId);
      const failed = result.sources.filter((source) => source.status === 'failed').length;
      setSourceResult(failed ? t('knowledge:results.reindexedSourcesWithFailures', { count: result.sources.length - failed, failed }) : t('knowledge:results.reindexedSources', { count: result.sources.length }));
    } catch (error) {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) {
        setSourceError(toSettingsError(error, 'Failed to reindex knowledge base.'));
      }
    } finally {
      if (currentKnowledgeBaseIdRef.current === knowledgeBaseId) setBusy('');
    }
  }
  async function runSearch() {
    if (!values.id || !searchQuery.trim()) return;
    const knowledgeBaseId = values.id;
    const requestId = searchRequestRef.current + 1;
    searchRequestRef.current = requestId;
    setBusy('searching');
    try {
      setSearchError(null);
      setSearchResponse(null);
      const response = await api.searchKnowledge({ query: searchQuery, knowledge_base_ids: [knowledgeBaseId], debug: true });
      if (searchRequestRef.current === requestId && currentKnowledgeBaseIdRef.current === knowledgeBaseId) {
        setSearchResponse(response);
      }
    } catch (error) {
      if (searchRequestRef.current === requestId && currentKnowledgeBaseIdRef.current === knowledgeBaseId) {
        setSearchError(toSettingsError(error, 'Knowledge search failed.'));
      }
    } finally {
      if (searchRequestRef.current === requestId && currentKnowledgeBaseIdRef.current === knowledgeBaseId) {
        setBusy('');
      }
    }
  }
  return (
    <form className="settings-detail-form" onSubmit={save}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">{profileInitials(values.name || 'KB') || <BrainCircuit size={18} />}</div>
          <div>
            <h2>{values.name || t('knowledge:titles.newKnowledgeBase')}</h2>
            <div className="knowledge-header-chip-row">
              {'index_status' in values ? <KnowledgeIndexChip status={values.index_status || 'empty'} /> : <StatusChip tone="neutral">{t('status:common.unset', { ns: 'status' })}</StatusChip>}
              <StatusChip tone="neutral" className="knowledge-model-chip" title={embeddingProfileDebugTitle(values, selectedProfile, t)}>
                {selectedProfileName || t('knowledge:labels.missingEmbeddingModel')}
              </StatusChip>
            </div>
          </div>
        </div>
        <div className="settings-detail-actions">
          {activeTab === 'config' && configResult ? <span className="settings-badge success">{configResult}</span> : null}
          {activeTab === 'config' && dirty ? (
            <button className="settings-primary-button" type="submit" disabled={Boolean(busy)}>
              <Save size={14} />
              {busy === 'saving' ? t('common:saving') : t('common:save')}
            </button>
          ) : null}
          {!isNew ? <button className="settings-secondary-button danger" type="button" onClick={remove} disabled={Boolean(busy)}><Trash2 size={14} />{t('common:delete')}</button> : null}
          <ToggleSwitch checked={values.enabled ?? true} onChange={(checked) => setValues({ ...values, enabled: checked })} disabled={Boolean(busy)} />
        </div>
      </header>
      <DetailTabs
        tabs={[
          { id: 'config', label: t('knowledge:sections.config') },
          { id: 'manage_sources', label: t('knowledge:tabs.manageSources'), enabled: !isNew && Boolean(values.id) },
          { id: 'source_list', label: t('knowledge:tabs.sourceList'), enabled: !isNew && Boolean(values.id) },
          { id: 'search', label: t('knowledge:tabs.search'), enabled: !isNew && Boolean(values.id) },
        ]}
        activeTab={activeTab}
        onChange={(tab) => setActiveTab(tab as KnowledgeBaseTab)}
      />
      <div className="settings-detail-body">
        {activeTab === 'config' ? (
          <>
            {configError ? <SettingsApiError error={configError} /> : null}
            <section className="detail-section">
              <h3>{t('knowledge:sections.config')}</h3>
              <div className="settings-detail-grid">
                <TextField label={t('knowledge:labels.name')} value={values.name || ''} onChange={(value) => setValues({ ...values, name: value })} />
                <SelectField label={t('knowledge:labels.embeddingModelProfile')} value={values.embedding_model_profile_id || ''} options={profiles.map((profile) => profile.id)} labels={Object.fromEntries(profiles.map((profile) => [profile.id, profile.name]))} onChange={(value) => setValues({ ...values, embedding_model_profile_id: value })} />
              </div>
              <TextAreaField label={t('knowledge:labels.aliases')} value={values.aliases_text || ''} onChange={(value) => setValues({ ...values, aliases_text: value })} />
              <p className="settings-muted-text">{t('knowledge:help.aliases')}</p>
              <TextAreaField label={t('knowledge:labels.description')} value={values.description || ''} onChange={(value) => setValues({ ...values, description: value })} />
              {'index_status' in values ? <dl className="settings-definition-grid"><Metric label={t('knowledge:labels.indexStatus')} value={getKnowledgeIndexStatusLabel(values.index_status || 'empty', t)} /></dl> : null}
            </section>
            <section className="detail-section">
              <h3>{t('knowledge:sections.overrides')}</h3>
              <div className="settings-detail-grid">
                <NumberField label={t('knowledge:labels.chunkSizeOverride')} value={values.chunk_size_override ?? ''} onChange={(value) => setValues({ ...values, chunk_size_override: value === '' ? null : Number(value) })} />
                <NumberField label={t('knowledge:labels.chunkOverlapOverride')} value={values.chunk_overlap_override ?? ''} onChange={(value) => setValues({ ...values, chunk_overlap_override: value === '' ? null : Number(value) })} />
                <NumberField label={t('knowledge:labels.vectorCandidateKOverride')} value={values.vector_candidate_k_override ?? ''} onChange={(value) => setValues({ ...values, vector_candidate_k_override: value === '' ? null : Number(value) })} />
                <NumberField label={t('knowledge:labels.keywordCandidateKOverride')} value={values.keyword_candidate_k_override ?? ''} onChange={(value) => setValues({ ...values, keyword_candidate_k_override: value === '' ? null : Number(value) })} />
                <NumberField label={t('knowledge:labels.finalTopKOverride')} value={values.final_top_k_override ?? ''} onChange={(value) => setValues({ ...values, final_top_k_override: value === '' ? null : Number(value) })} />
                <NumberField label={t('knowledge:labels.maxContextCharsOverride')} value={values.max_context_chars_override ?? ''} onChange={(value) => setValues({ ...values, max_context_chars_override: value === '' ? null : Number(value) })} />
                <SelectField
                  label={t('knowledge:labels.defaultChunkProfile')}
                  value={values.default_chunk_profile || 'markdown_auto'}
                  options={CHUNK_PROFILES}
                  labels={chunkProfileLabels(t)}
                  onChange={(value) => setValues({ ...values, default_chunk_profile: value as ChunkProfile })}
                />
              </div>
            </section>
          </>
        ) : null}
        {activeTab === 'manage_sources' && !isNew && values.id ? (
          <>
            <section className="detail-section">
              <div className="knowledge-source-toolbar">
                <button className="settings-primary-button" type="button" disabled={Boolean(busy)} onClick={() => openSourceModal('create_origin')}>
                  <FolderPlus size={14} />
                  {t('knowledge:actions.createOrigin')}
                </button>
                <button className="settings-secondary-button" type="button" disabled={Boolean(busy)} onClick={() => openSourceModal('import_files')}>
                  <Upload size={14} />
                  {t('knowledge:actions.importFiles')}
                </button>
                <button className="settings-secondary-button" type="button" disabled={Boolean(busy)} onClick={() => openSourceModal('paste_text')}>
                  <Clipboard size={14} />
                  {t('knowledge:actions.pasteText')}
                </button>
              </div>
              {sourceResult ? <span className="settings-badge success">{sourceResult}</span> : null}
              {sourceError ? <SettingsApiError error={sourceError} /> : null}
            </section>
            <section className="detail-section">
              <div className="detail-section-heading"><h3>{t('knowledge:sections.origins')}</h3></div>
              {origins.length ? (
                <div className="knowledge-origin-list">
                  {origins.map((origin) => (
                    <OriginAccordionCard
                      key={origin.id}
                      origin={origin}
                      sources={sources}
                      kbDefaultProfile={values.default_chunk_profile || null}
                      expanded={expandedOriginIds.has(origin.id)}
                      busy={busy}
                      onToggle={() => setExpandedOriginIds((current) => {
                        const next = new Set(current);
                        if (next.has(origin.id)) next.delete(origin.id);
                        else next.add(origin.id);
                        return next;
                      })}
                      onScan={() => scanOrigin(origin.id)}
                      onReindex={() => importOrigin(origin.id)}
                      onDelete={() => deleteOrigin(origin)}
                    />
                  ))}
                </div>
              ) : <Empty title={t('knowledge:empty.noOrigins')} message={t('knowledge:empty.noOriginsMessage')} />}
            </section>
          </>
        ) : null}
        {activeTab === 'source_list' && !isNew && values.id ? (
          <>
            <section className="detail-section">
              {sourceResult ? <span className="settings-badge success">{sourceResult}</span> : null}
              {sourceError ? <SettingsApiError error={sourceError} /> : null}
              <div className="detail-section-heading">
                <h3>{t('knowledge:sections.sourcesList')}</h3>
                {hasStaleOriginSources ? <span className="settings-badge warning">{t('knowledge:statusText.reindexRecommended')}</span> : null}
                <button className="settings-secondary-button" type="button" disabled={!sources.length || Boolean(busy)} onClick={reindexAllSources}>
                  <RefreshCw size={14} />
                  {busy === 'reindexing all' ? t('knowledge:actions.reindexing') : t('knowledge:actions.reindexAll')}
                </button>
              </div>
              {sources.length ? (
                <SourcesTable
                  sources={sortedSources}
                  sort={sourceSort}
                  onSort={toggleSourceSort}
                  selectedSourceId={selectedSourceId}
                  onSelect={setSelectedSourceId}
                  onReindex={reindexSource}
                  onDelete={deleteSource}
                  busy={busy}
                />
              ) : <Empty title={t('knowledge:empty.noSources')} message={t('knowledge:empty.noSourcesMessage')} />}
            </section>
            {selectedSource ? (
              <SourceDetail
                source={selectedSource}
                preview={sourcePreview}
                chunks={sourceChunks}
                loading={sourceDetailLoading}
                error={sourceDetailError}
                busy={busy}
                onClose={() => setSelectedSourceId('')}
                onReindex={() => reindexSource(selectedSource.id)}
                onDelete={() => deleteSource(selectedSource.id)}
              />
            ) : null}
          </>
        ) : null}
        {activeTab === 'search' && !isNew && values.id ? (
          <section className="detail-section">
            <div className="detail-section-heading"><h3>{t('knowledge:sections.searchTest')}</h3></div>
            <div className="settings-detail-grid">
              <TextField label={t('knowledge:labels.query')} value={searchQuery} onChange={setSearchQuery} />
            </div>
            <div className="settings-button-row">
              <button className="settings-secondary-button" type="button" disabled={!searchQuery.trim() || Boolean(busy)} onClick={runSearch}>
                {busy === 'searching' ? <LoadingSpinner /> : <Search size={14} />}
                {t('knowledge:actions.search')}
              </button>
            </div>
            {searchError ? <SettingsApiError error={searchError} /> : null}
            {searchResponse ? <KnowledgeSearchResults response={searchResponse} /> : null}
          </section>
        ) : null}
        {activeTab !== 'config' && (isNew || !values.id) ? <Empty title={t('knowledge:empty.saveFirst')} message={t('knowledge:empty.saveFirstMessage')} /> : null}
      </div>
      <AppModal open={sourceModal === 'create_origin'} title={t('knowledge:modals.createOriginTitle')} closeLabel={t('common:close')} bodyClassName="knowledge-modal-shell" onClose={closeSourceModal}>
        <div className="knowledge-modal-body">
          <div className="knowledge-source-modal-form">
            <div className="knowledge-origin-create-row">
              <TextField label={t('knowledge:labels.originName')} value={originName} onChange={setOriginName} />
              <SelectField label={t('knowledge:labels.originChunkProfileOverride')} value={originDefaultChunkProfile} options={CHUNK_PROFILES} labels={chunkProfileLabels(t)} placeholder={t('knowledge:placeholders.noOverride')} onChange={setOriginDefaultChunkProfile} />
              <label className="knowledge-index-toggle-row" title={t('knowledge:help.indexAfterCreateShort')}>
                <span>{t('knowledge:labels.indexAfterCreate')}</span>
                <MiniToggle checked={originIndexAfterCreate} onChange={setOriginIndexAfterCreate} disabled={Boolean(busy)} />
              </label>
            </div>
            <label className="config-field settings-config-field knowledge-origin-folder-field">
              <span>{t('knowledge:labels.originFolder')}</span>
              <div className="knowledge-origin-folder-combobox">
                <div className="knowledge-origin-folder-input" ref={originFolderInputRef}>
                  <code>data/knowledge/origins/</code>
                  <input
                    className="settings-form-control"
                    type="text"
                    value={originSlug}
                    placeholder={t('knowledge:placeholders.originFolder')}
                    onChange={(event) => {
                      setOriginSlug(event.currentTarget.value);
                      setOriginFolderSuggestionsOpen(true);
                    }}
                    onFocus={() => {
                      setOriginFolderSuggestionsOpen(true);
                      window.setTimeout(updateOriginFolderPopupRect, 0);
                    }}
                    onBlur={() => setOriginFolderSuggestionsOpen(false)}
                    onKeyDown={onOriginFolderKeyDown}
                    role="combobox"
                    aria-expanded={showOriginFolderSuggestions}
                    aria-autocomplete="list"
                  />
                </div>
              </div>
              {showOriginFolderSuggestions && originFolderPopupRect ? createPortal(
                <div
                  className="knowledge-folder-suggestion-popup floating"
                  role="listbox"
                  style={{ left: originFolderPopupRect.left, top: originFolderPopupRect.top, width: originFolderPopupRect.width }}
                >
                  {originFolderSuggestionsLoading ? <div className="knowledge-folder-suggestion-status">{t('knowledge:labels.loadingSuggestions')}</div> : null}
                  {visibleOriginFolderSuggestions.map((folder, index) => (
                    <button
                      className={index === originFolderSuggestionActiveIndex ? 'active' : ''}
                      key={folder.path}
                      type="button"
                      role="option"
                      aria-selected={index === originFolderSuggestionActiveIndex}
                      onMouseEnter={() => setOriginFolderSuggestionActiveIndex(index)}
                      onMouseDown={(event) => {
                        event.preventDefault();
                        selectOriginFolderSuggestion(folder.path);
                      }}
                    >
                      {folder.path}
                    </button>
                  ))}
                </div>,
                document.body,
              ) : null}
              <small>{t('knowledge:help.originFolderShort')}</small>
              {originFolderSuggestionError ? <small className="settings-error-text">{t('knowledge:errors.loadOriginFoldersFailed')}</small> : null}
            </label>
            {modalError ? <SettingsApiError error={modalError} /> : null}
          </div>
        </div>
        <div className="knowledge-modal-footer">
          <div className="settings-button-row">
            <button className="settings-primary-button" type="button" disabled={!originName.trim() || !originSlug.trim() || Boolean(busy)} onClick={() => createOrigin(originIndexAfterCreate)}>
              {busy === 'creating origin' ? <LoadingSpinner /> : <FolderPlus size={14} />}
              {originIndexAfterCreate ? t('knowledge:actions.createAndIndex') : t('knowledge:actions.create')}
            </button>
          </div>
        </div>
      </AppModal>
      <AppModal open={sourceModal === 'import_files'} title={t('knowledge:modals.importFilesTitle')} closeLabel={t('common:close')} bodyClassName="knowledge-modal-shell" onClose={closeSourceModal}>
        <div className="knowledge-modal-body">
        <div className="knowledge-source-modal-form">
          <input ref={fileInputRef} className="sr-only" type="file" multiple accept={TEXT_ATTACHMENT_ACCEPT} onChange={onFileChange} />
          <button
            className={`knowledge-file-dropzone ${importDragActive ? 'active' : ''}`}
            type="button"
            disabled={Boolean(busy)}
            onClick={() => fileInputRef.current?.click()}
            onDragOver={onImportDragOver}
            onDragLeave={onImportDragLeave}
            onDrop={onImportDrop}
          >
            <FileText size={14} />
            <span>
              <strong>{t('knowledge:dropzone.title')}</strong>
              <small>{t('knowledge:dropzone.description')}</small>
            </span>
          </button>
          {importFiles.length ? (
            <div className="knowledge-selected-file-list">
              {importFiles.map((file, index) => (
                <div className="knowledge-selected-file" key={`${file.name}:${file.size}:${file.lastModified}`}>
                  <FileText size={14} />
                  <span>
                    <strong>{file.name}</strong>
                    <small>{fileExtension(file.name) || file.type || t('status:common.unknown', { ns: 'status' })} · {formatBytes(file.size)}</small>
                  </span>
                  <button className="icon-button" type="button" onClick={() => removeImportFile(index)} aria-label={t('knowledge:actions.removeFile')}>
                    <X size={14} />
                  </button>
                </div>
              ))}
            </div>
          ) : <p className="settings-muted-text">{t('knowledge:empty.noFilesSelected')}</p>}
          <div className="settings-detail-grid">
            <TextField label={t('knowledge:labels.sourcesFolderPath')} value={sourceFolderPath} placeholder={t('knowledge:placeholders.kbRootFolder')} onChange={setSourceFolderPath} />
            <SelectField label={t('knowledge:labels.chunkProfileOverride')} value={sourceChunkProfile} options={CHUNK_PROFILES} labels={chunkProfileLabels(t)} placeholder={t('knowledge:placeholders.noOverride')} onChange={setSourceChunkProfile} />
          </div>
          <p className="settings-muted-copy">{t('knowledge:help.sourcesFolderPathShort')}</p>
          {modalError ? <SettingsApiError error={modalError} /> : null}
        </div>
        </div>
        <div className="knowledge-modal-footer">
          <div className="settings-button-row">
            <button className="settings-primary-button" type="button" disabled={!importFiles.length || Boolean(busy)} onClick={() => addFiles(importFiles, { folderPath: sourceFolderPath, chunkProfile: sourceChunkProfile || null })}>
              {busy === 'indexing file' ? <LoadingSpinner /> : <Play size={14} />}
              {t('knowledge:actions.index')}
            </button>
          </div>
        </div>
      </AppModal>
      <AppModal open={sourceModal === 'paste_text'} title={t('knowledge:modals.pasteTextTitle')} closeLabel={t('common:close')} bodyClassName="knowledge-modal-shell" onClose={closeSourceModal}>
        <div className="knowledge-modal-body">
        <div className="knowledge-source-modal-form">
          <div className="settings-detail-grid">
            <TextField label={t('knowledge:labels.title')} value={sourceTitle} onChange={setSourceTitle} />
            <TextField label={t('knowledge:labels.sourcesFolderPath')} value={sourceFolderPath} placeholder={t('knowledge:placeholders.kbRootFolder')} onChange={setSourceFolderPath} />
            <SelectField label={t('knowledge:labels.chunkProfileOverride')} value={sourceChunkProfile} options={CHUNK_PROFILES} labels={chunkProfileLabels(t)} placeholder={t('knowledge:placeholders.noOverride')} onChange={setSourceChunkProfile} />
          </div>
          <TextAreaField label={t('knowledge:labels.textContent')} value={sourceText} onChange={setSourceText} />
          <p className="settings-muted-copy">{t('knowledge:help.sourcesFolderPathShort')}</p>
          {modalError ? <SettingsApiError error={modalError} /> : null}
        </div>
        </div>
        <div className="knowledge-modal-footer">
          <div className="settings-button-row">
            <button className="settings-primary-button" type="button" disabled={!sourceTitle.trim() || !sourceText.trim() || Boolean(busy)} onClick={addPastedSource}>
              {busy === 'indexing' ? <LoadingSpinner /> : <Play size={14} />}
              {t('knowledge:actions.index')}
            </button>
          </div>
        </div>
      </AppModal>
    </form>
  );
}

function KnowledgeSearchResults({ response }: { response: KnowledgeSearchResponse }) {
  const { t } = useTranslation(['knowledge', 'common']);
  return (
    <div className="knowledge-search-results">
      {response.results.length ? response.results.map((result) => (
        <article className="knowledge-result-card" key={result.chunk_id}>
          <div className="knowledge-result-rank">#{result.rank}</div>
          <div className="knowledge-result-body">
            <div className="knowledge-result-title">
              <strong>{result.title || result.source_id}</strong>
              {result.heading_path ? <span>{result.heading_path}</span> : null}
            </div>
            <p>{result.content}{result.truncated ? '...' : ''}</p>
            <div className="settings-chip-row knowledge-score-row">
              <span>Vector <small>{rankScoreLabel(result.vector_rank, result.vector_score)}</small></span>
              <span>Keyword <small>{rankScoreLabel(result.keyword_rank, result.keyword_score)}</small></span>
              <span>RRF <small>{scoreLabel(result.rrf_score)}</small></span>
              <span>Rerank <small>{scoreLabel(result.rerank_score)}</small></span>
            </div>
          </div>
        </article>
      )) : <Empty title={t('knowledge:empty.noResults')} message={t('knowledge:empty.noResultsMessage')} />}
      {response.debug ? (
        <details className="settings-debug-details">
          <summary>{t('common:details')}</summary>
          <pre>{JSON.stringify(response.debug, null, 2)}</pre>
        </details>
      ) : null}
      <details className="knowledge-context-preview" open>
        <summary>{t('knowledge:labels.contextPreview')}</summary>
        {response.context_preview ? (
          <pre>{response.context_preview}</pre>
        ) : (
          <p className="settings-muted-text">{t('knowledge:empty.noContext')}</p>
        )}
      </details>
    </div>
  );
}

function OriginAccordionCard({
  origin,
  sources,
  kbDefaultProfile,
  expanded,
  busy,
  onToggle,
  onScan,
  onReindex,
  onDelete,
}: {
  origin: KnowledgeOrigin;
  sources: KnowledgeSource[];
  kbDefaultProfile: string | null;
  expanded: boolean;
  busy: string;
  onToggle: () => void;
  onScan: () => void;
  onReindex: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation(['knowledge', 'status']);
  const originSources = sources.filter((source) => source.origin_id === origin.id);
  const newCount = originSources.filter((source) => source.file_status === 'new').length;
  const changedCount = originSources.filter((source) => source.file_status === 'changed' || source.status === 'needs_reindex').length;
  const missingCount = originSources.filter((source) => source.file_status === 'missing').length;
  const reindexDisabled = !newCount && !changedCount && !missingCount;
  return (
    <article className={`knowledge-origin-card ${expanded ? 'expanded' : ''}`}>
      <button className="knowledge-origin-card-header" type="button" onClick={onToggle} aria-expanded={expanded}>
        <ChevronDown className="knowledge-origin-chevron" size={16} />
        <div className="knowledge-origin-title">
          <strong>{origin.name}</strong>
          <small>{origin.root_path || `data/knowledge/origins/${origin.slug}`}</small>
        </div>
      </button>
      <div className="knowledge-origin-actions" onClick={(event) => event.stopPropagation()}>
        <button className="settings-secondary-button" type="button" disabled={Boolean(busy)} onClick={onScan}>
          <Search size={14} />
          {busy === `scan origin:${origin.id}` ? t('knowledge:actions.scanning') : t('knowledge:actions.scan')}
        </button>
        <button className="settings-secondary-button" type="button" disabled={reindexDisabled || Boolean(busy)} onClick={onReindex}>
          <RefreshCw size={14} />
          {busy === `import origin:${origin.id}` ? t('knowledge:actions.reindexing') : t('knowledge:actions.reindex')}
        </button>
      </div>
      {expanded ? (
        <div className="knowledge-origin-card-body">
          <dl className="settings-definition-grid">
            <Metric label={t('knowledge:labels.lastScan')} value={formatDate(origin.last_scan_at, t('status:common.none', { ns: 'status' }))} />
            <Metric label={t('knowledge:labels.defaultChunkProfile')} value={originProfileText(origin.default_chunk_profile || null, kbDefaultProfile, t)} />
            <Metric label={t('knowledge:labels.totalFiles')} value={String(originSources.length)} />
            <Metric label={t('knowledge:labels.newFiles')} value={String(newCount)} />
            <Metric label={t('knowledge:labels.changedFiles')} value={String(changedCount)} />
            <Metric label={t('knowledge:labels.missingFiles')} value={String(missingCount)} />
          </dl>
          {origin.error ? <p className="settings-error-text">{origin.error}</p> : null}
          <div className="knowledge-origin-danger-zone">
            <p>{t('knowledge:help.deleteOriginKeepsFiles')}</p>
            <button className="settings-secondary-button danger" type="button" disabled={Boolean(busy)} onClick={onDelete}>
              <Trash2 size={14} />
              {t('knowledge:actions.deleteOrigin')}
            </button>
          </div>
        </div>
      ) : null}
    </article>
  );
}

function SourcesTable({ sources, sort, onSort, selectedSourceId, onSelect, onReindex, onDelete, busy }: {
  sources: KnowledgeSource[];
  sort: { key: SourceSortKey; direction: SortDirection };
  onSort: (key: SourceSortKey) => void;
  selectedSourceId: string;
  onSelect: (sourceId: string) => void;
  onReindex: (sourceId: string) => void;
  onDelete: (sourceId: string) => void;
  busy: string;
}) {
  const { t } = useTranslation(['knowledge', 'common', 'status']);
  return (
    <div className="knowledge-table-scroll">
      <table className="knowledge-sources-table">
        <thead>
          <tr>
            <SortableHeader label={t('knowledge:labels.source')} sortKey="title" activeSort={sort} onSort={onSort} />
            <SortableHeader label={t('knowledge:labels.folder')} sortKey="folder_path" activeSort={sort} onSort={onSort} />
            <SortableHeader label={t('knowledge:labels.type')} sortKey="source_type" activeSort={sort} onSort={onSort} />
            <SortableHeader label={t('knowledge:labels.chunks')} sortKey="chunks" activeSort={sort} onSort={onSort} />
            <SortableHeader label={t('knowledge:labels.index')} sortKey="indexed_at" activeSort={sort} onSort={onSort} />
            <th>{t('knowledge:labels.actions')}</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((source) => (
            <tr className={source.id === selectedSourceId ? 'selected' : ''} key={source.id} onClick={() => onSelect(source.id)}>
              <SourceNameCell source={source} />
              <td className="knowledge-source-folder-cell" title={source.folder_path || t('status:common.none', { ns: 'status' })}>
                {source.folder_path || t('status:common.none', { ns: 'status' })}
              </td>
              <td>{source.source_type}</td>
              <td>{source.chunks}</td>
              <td><SourceIndexCell source={source} /></td>
              <td className="knowledge-source-actions-cell">
                <div className="settings-button-row compact" onClick={(event) => event.stopPropagation()}>
                  <button className="settings-secondary-button icon-only" type="button" onClick={() => onReindex(source.id)} disabled={Boolean(busy)} aria-label={t('knowledge:actions.reindex')} title={t('knowledge:actions.reindex')}><RefreshCw size={14} /></button>
                  <button className="settings-secondary-button icon-only danger" type="button" onClick={() => onDelete(source.id)} disabled={Boolean(busy)} aria-label={t('common:delete')} title={t('common:delete')}><Trash2 size={14} /></button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SourceNameCell({ source }: { source: KnowledgeSource }) {
  const { t } = useTranslation('knowledge');
  const title = sourceListTitle(source, t);
  const subtitle = sourceListSubtitle(source);
  return (
    <td>
      <strong title={title}>{title}</strong>
      {subtitle ? <small title={subtitle}>{subtitle}</small> : null}
      {source.error ? <small className="settings-error-text">{source.error}</small> : null}
    </td>
  );
}

function SourceDetail({ source, preview, chunks, loading, error, busy, onClose, onReindex, onDelete }: {
  source: KnowledgeSource;
  preview: KnowledgeSourcePreview | null;
  chunks: KnowledgeSourceChunk[];
  loading: boolean;
  error: SettingsErrorValue | null;
  busy: string;
  onClose: () => void;
  onReindex: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation(['knowledge', 'common', 'status']);
  const lastIndexed = formatDate(source.indexed_at, t('status:common.notIndexed', { ns: 'status' }));
  const lastIndexedLabel = t('knowledge:labels.lastIndexedAtValue', { value: lastIndexed });
  return (
    <div className="preview-backdrop" role="dialog" aria-modal="true" aria-label={t('knowledge:labels.sourceDetail')} onClick={onClose}>
      <section className="knowledge-source-modal" onClick={(event) => event.stopPropagation()}>
        <header className="knowledge-source-modal-header">
          <div>
            <h3>{sourceListTitle(source, t)}</h3>
            <div className="settings-chip-row">
              <span>{source.source_type}</span>
              <span>{getKnowledgeSourceStatusLabel(source.file_status || source.status, t)}</span>
              <span title={lastIndexedLabel}>{lastIndexedLabel}</span>
            </div>
          </div>
          <div className="settings-button-row compact">
            <button className="settings-secondary-button" type="button" onClick={onReindex} disabled={Boolean(busy)}><RefreshCw size={14} />{t('knowledge:actions.reindex')}</button>
            <button className="settings-secondary-button danger" type="button" onClick={onDelete} disabled={Boolean(busy)}><Trash2 size={14} />{t('common:delete')}</button>
            <button className="settings-secondary-button icon-only" type="button" onClick={onClose} aria-label={t('knowledge:actions.closeSourceDetail')}><X size={16} /></button>
          </div>
        </header>
        <div className="knowledge-source-modal-body">
          {error ? <SettingsApiError error={error} /> : null}
          <section className="knowledge-source-subsection">
            <h4>{t('knowledge:sections.overview')}</h4>
            <dl className="settings-definition-grid knowledge-source-overview-row first">
              <Metric label={t('knowledge:labels.chunks')} value={String(source.chunks)} />
              <Metric label={t('knowledge:labels.embeddingDimension')} value={source.embedding_dimension ? String(source.embedding_dimension) : 'n/a'} />
              <Metric label={t('knowledge:labels.confidence')} value={confidenceLabel(source.chunk_profile_confidence ?? source.metadata?.chunk_profile_confidence, t)} />
              <Metric label={t('knowledge:labels.entityLevel')} value={entityLevelLabel(source.entity_level ?? source.metadata?.entity_level, t)} />
            </dl>
            <dl className="settings-definition-grid knowledge-source-overview-row second">
              <Metric label={t('knowledge:labels.contentHash')} value={source.content_hash || 'n/a'} valueClassName="knowledge-content-hash-value" />
              <Metric label={t('knowledge:labels.size')} value={formatBytes(source.size_bytes)} />
            </dl>
            <dl className="settings-definition-grid knowledge-source-overview-row third">
              <Metric label={t('knowledge:labels.effectiveProfile')} value={sourceProfileText(source, t)} />
              <Metric label={t('knowledge:labels.profileSource')} value={profileSourceLabel(source.profile_source || source.metadata?.profile_source, t)} />
              <Metric label={t('knowledge:labels.titleSource')} value={profileSourceLabel(source.title_source || source.metadata?.title_source, t)} />
              <Metric label={t('knowledge:labels.typeSource')} value={profileSourceLabel(source.type_source || source.metadata?.type_source, t)} />
            </dl>
            {source.error ? <p className="settings-error-text">{source.error}</p> : null}
          </section>
          <section className="knowledge-source-subsection">
            <div className="detail-section-heading">
              <h4>{t('knowledge:sections.sourcePreview')}</h4>
              {preview?.truncated ? <span className="settings-badge warning">truncated</span> : null}
            </div>
            {loading && !preview ? <p className="settings-muted-text">{t('common:loading')}</p> : null}
            {!loading && !preview && !error ? <p className="settings-muted-text">{t('knowledge:empty.sourcePreviewUnavailable')}</p> : null}
            {preview ? <pre className="knowledge-source-preview">{preview.preview}</pre> : null}
          </section>
          <section className="knowledge-source-subsection">
            <div className="detail-section-heading">
              <h4>{t('knowledge:sections.chunks')}</h4>
              <span className="settings-badge muted">{chunks.length}</span>
            </div>
            {loading && !chunks.length ? <p className="settings-muted-text">{t('common:loading')}</p> : null}
            {!loading && !chunks.length ? <Empty title={t('knowledge:empty.noChunks')} message={t('knowledge:empty.noChunksMessage')} /> : null}
            {chunks.length ? (
              <div className="knowledge-chunk-list">
                {chunks.map((chunk) => (
                  <details className="knowledge-chunk-card" key={chunk.chunk_id} open={chunk.chunk_index < 3}>
                    <summary>
                      <strong>{t('knowledge:labels.chunkNumber', { index: chunk.chunk_index })}</strong>
                      <span>{chunk.char_start}-{chunk.char_end}</span>
                      {chunk.embedding_dimension ? <span>{chunk.embedding_dimension}d</span> : null}
                      {chunk.metadata?.chunk_profile_effective ? <span>{chunkProfileLabel(String(chunk.metadata.chunk_profile_effective), t)}</span> : null}
                    </summary>
                    {chunk.heading_path ? <small>{chunk.heading_path}</small> : null}
                    {chunk.metadata ? (
                      <div className="settings-chip-row">
                        <span>{profileReasonText(chunk.metadata, t)}</span>
                        <span>{t('knowledge:labels.titleSource')}: {profileSourceLabel(chunk.metadata.title_source, t)}</span>
                        <span>{t('knowledge:labels.typeSource')}: {profileSourceLabel(chunk.metadata.type_source, t)}</span>
                      </div>
                    ) : null}
                    <pre>{chunk.content_preview || chunk.content}{chunk.truncated ? '\n...' : ''}</pre>
                  </details>
                ))}
              </div>
            ) : null}
          </section>
        </div>
      </section>
    </div>
  );
}

function SourceIndexCell({ source }: { source: KnowledgeSource }) {
  const { t } = useTranslation(['knowledge', 'status']);
  const status = sourceIndexStatus(source);
  const indexedAt = formatDate(source.indexed_at, t('status:common.notIndexed', { ns: 'status' }));
  const indexedTitle = t('knowledge:labels.lastIndexedAtValue', { value: indexedAt });
  return (
    <div className="knowledge-source-index-cell" title={indexedTitle}>
      <StatusChip tone={knowledgeSourceTone(status)}>
        {getKnowledgeSourceStatusLabel(status, t)}
      </StatusChip>
      {source.indexed_at ? <small>{indexedAt}</small> : null}
    </div>
  );
}

function KnowledgeIndexChip({ status }: { status: string }) {
  const { t } = useTranslation('status');
  return <StatusChip tone={knowledgeIndexTone(status)}>{getKnowledgeIndexStatusLabel(status, t)}</StatusChip>;
}

function knowledgeIndexTone(status: string): 'neutral' | 'active' | 'warning' | 'danger' {
  if (status === 'ready') return 'active';
  if (status === 'indexing') return 'warning';
  if (['needs_reindex', 'needs_index', 'failed'].includes(status)) return 'danger';
  return 'neutral';
}

function knowledgeSourceTone(status: string): 'neutral' | 'active' | 'warning' | 'danger' {
  if (status === 'ready' || status === 'indexed') return 'active';
  if (status === 'indexing' || status === 'pending' || status === 'new' || status === 'changed' || status === 'missing' || status === 'needs_reindex') return 'warning';
  if (status === 'failed') return 'danger';
  return 'neutral';
}

function embeddingProfileDebugTitle(values: Partial<KnowledgeBase>, profile: EmbeddingModelProfile | undefined, t: ReturnType<typeof useTranslation>['t']): string {
  const alias = values.embedding_model_profile_alias || profile?.alias || values.embedding_model_profile_id || '';
  const path = values.embedding_model_profile_model_path || profile?.model_path || '';
  const dimension = values.embedding_model_profile_dimension ?? profile?.dimension;
  return [
    alias ? `${t('knowledge:labels.profileKey')}: ${alias}` : '',
    path ? `${t('knowledge:labels.modelPath')}: ${path}` : '',
    dimension ? `${t('knowledge:labels.dimension')}: ${dimension}` : '',
  ].filter(Boolean).join('\n');
}

function originProfileText(originProfile: string | null, kbDefaultProfile: string | null, t: ReturnType<typeof useTranslation>['t']): string {
  if (originProfile) {
    return t('knowledge:labels.profileWithSource', {
      profile: chunkProfileLabel(originProfile, t),
      source: t('knowledge:profileSourcePhrases.originOverride'),
    });
  }
  return t('knowledge:labels.profileWithSource', {
    profile: chunkProfileLabel(kbDefaultProfile || 'markdown_auto', t),
    source: t('knowledge:profileSourcePhrases.inheritedFromKnowledgeBase'),
  });
}

function SortableHeader({ label, sortKey, activeSort, onSort }: { label: string; sortKey: SourceSortKey; activeSort: { key: SourceSortKey; direction: SortDirection }; onSort: (key: SourceSortKey) => void }) {
  const active = activeSort.key === sortKey;
  return (
    <th aria-sort={active ? (activeSort.direction === 'asc' ? 'ascending' : 'descending') : undefined}>
      <button className="knowledge-sort-button" type="button" onClick={() => onSort(sortKey)} aria-label={label} title={label}>
        {label}
        {active ? <ChevronDown className={activeSort.direction === 'asc' ? 'asc' : undefined} size={12} aria-hidden="true" /> : <ArrowUpDown size={12} aria-hidden="true" />}
      </button>
    </th>
  );
}

function scoreLabel(value?: number | null): string {
  return typeof value === 'number' ? value.toFixed(4) : 'n/a';
}

function rankScoreLabel(rank?: number | null, score?: number | null): string {
  const rankText = typeof rank === 'number' ? `#${rank}` : 'n/a';
  return `${rankText} / ${scoreLabel(score)}`;
}

function NumberGroup({ title, values, setValues, fields }: { title: string; values: KnowledgeSettings; setValues: (values: KnowledgeSettings) => void; fields: [keyof KnowledgeSettings, string][] }) {
  return (
    <div className="detail-section">
      <div className="detail-section-heading"><h3>{title}</h3></div>
      <div className="settings-detail-grid">
        {fields.map(([key, label]) => (
          <NumberField key={String(key)} label={label} value={values[key] as number} onChange={(value) => {
            if (value !== '') setValues({ ...values, [key]: value });
          }} />
        ))}
      </div>
    </div>
  );
}

function TextField({ label, value, placeholder, onChange }: { label: string; value: string; placeholder?: string; onChange: (value: string) => void }) {
  return <label className="config-field settings-config-field"><span>{label}</span><input className="settings-form-control" type="text" value={value} placeholder={placeholder} onChange={(event) => onChange(event.currentTarget.value)} /></label>;
}

function NumberField({ label, value, onChange }: { label: string; value: number | string; onChange: (value: number | '') => void }) {
  return <label className="config-field settings-config-field"><span>{label}</span><input className="settings-form-control" type="number" value={value} onChange={(event) => onChange(event.currentTarget.value === '' ? '' : Number(event.currentTarget.value))} /></label>;
}

function TextAreaField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label className="config-field settings-config-field"><span>{label}</span><textarea className="settings-form-control" rows={6} value={value} onChange={(event) => onChange(event.currentTarget.value)} /></label>;
}

function SelectField({ label, value, options, labels, placeholder, disabled, onChange }: { label: string; value: string; options: string[]; labels?: Record<string, string>; placeholder?: string; disabled?: boolean; onChange: (value: string) => void }) {
  const optionValues = value && !options.includes(value) ? [value, ...options] : options;
  return (
    <label className="config-field settings-config-field">
      <span>{label}</span>
      <select className="settings-form-control" value={value} disabled={disabled} onChange={(event) => onChange(event.currentTarget.value)}>
        {placeholder ? <option value="">{placeholder}</option> : null}
        {optionValues.map((option) => <option key={option} value={option}>{labels?.[option] || option}</option>)}
      </select>
    </label>
  );
}

function Metric({ label, value, valueClassName }: { label: string; value: string; valueClassName?: string }) {
  return <div><dt>{label}</dt><dd className={valueClassName} title={value}>{value}</dd></div>;
}

function LoadingSpinner() {
  return <Loader2 className="spin" size={14} aria-hidden="true" />;
}

function CommandCard({ command, title, onCopy }: { command: string; title?: string; onCopy: (text: string) => void }) {
  const { t } = useTranslation('knowledge');
  return (
    <div className="knowledge-command-card">
      <div className="knowledge-command-card-body">
        {title ? <strong>{title}</strong> : null}
        <code>{command}</code>
      </div>
      <button className="settings-secondary-button" type="button" onClick={() => onCopy(command)}>
        <Clipboard size={14} />
        {t('actions.copyCommand')}
      </button>
    </div>
  );
}

function ModelScanSummary({ scan }: { scan: KnowledgeModelScan }) {
  const { t } = useTranslation(['knowledge', 'status']);
  return (
    <dl className="settings-definition-grid">
      <Metric label={t('knowledge:labels.embeddingFolders')} value={String(scan.embedding_models.length)} />
      <Metric label={t('knowledge:labels.rerankerFolders')} value={String(scan.reranker_models.length)} />
      <Metric label="sentence-transformers" value={scan.backend.sentence_transformers_available ? t('status:common.available') : t('status:common.unavailable')} />
      <Metric label="torch" value={scan.backend.torch_available ? t('status:common.available') : t('status:common.unavailable')} />
    </dl>
  );
}

function backendLabel(backend: KnowledgeModelScan['backend'] | undefined, t: ReturnType<typeof useTranslation>['t']): string {
  if (!backend) return t('knowledge:backend.notScanned');
  return backend.available ? t('knowledge:backend.available') : t('knowledge:backend.unavailableOptionalDeps');
}

function dependencyLabel(value: boolean | undefined, t: ReturnType<typeof useTranslation>['t']): string {
  if (value === undefined) return t('knowledge:backend.notScanned');
  return value ? t('status:common.available') : t('status:common.unavailable');
}

function knowledgeSettingsPatch(values: KnowledgeSettings): Partial<KnowledgeSettings> {
  const { id, models_root, ...patch } = values;
  void id;
  void models_root;
  return patch;
}

function modelPathOptions(models: { model_path: string }[], currentPath: string): string[] {
  const paths = models.map((model) => model.model_path);
  return currentPath && !paths.includes(currentPath) ? [currentPath, ...paths] : paths;
}

function modelPathLabels(paths: string[]): Record<string, string> {
  return Object.fromEntries(paths.map((path) => [path, modelFolderName(path)]));
}

function normalizedOriginFolder(value: string): string {
  return value.replace(/\\/g, '/').replace(/^\/+/, '').replace(/\/{2,}/g, '/');
}

function originFolderParentPrefix(value: string): string {
  const normalized = normalizedOriginFolder(value);
  if (!normalized || normalized.endsWith('/')) return normalized;
  const slashIndex = normalized.lastIndexOf('/');
  return slashIndex >= 0 ? normalized.slice(0, slashIndex + 1) : '';
}

function originFolderSearchTerm(value: string): string {
  const normalized = normalizedOriginFolder(value);
  if (!normalized || normalized.endsWith('/')) return '';
  const slashIndex = normalized.lastIndexOf('/');
  return slashIndex >= 0 ? normalized.slice(slashIndex + 1) : normalized;
}

function originFolderLeafName(value: string): string {
  const normalized = normalizedOriginFolder(value).replace(/\/+$/, '');
  const slashIndex = normalized.lastIndexOf('/');
  return slashIndex >= 0 ? normalized.slice(slashIndex + 1) : normalized;
}

function embeddingPresetForPath(modelPath: string) {
  const folderName = modelFolderName(modelPath).toLowerCase();
  return KNOWLEDGE_MODEL_PRESETS.find((preset) => preset.type === 'embedding' && preset.target.toLowerCase() === folderName && preset.profile);
}

function modelFolderName(modelPath: string): string {
  const normalized = modelPath.replace(/\\/g, '/').replace(/\/+$/, '');
  const parts = normalized.split('/').filter(Boolean);
  return parts[parts.length - 1] || modelPath;
}

function safeProfileKey(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'embedding-model';
}

function buildEmbeddingModelPayload(values: Partial<EmbeddingModelProfile>): EmbeddingModelProfileInput {
  return {
    name: values.name ?? '',
    alias: values.alias ?? '',
    model_path: values.model_path ?? '',
    dimension: parseOptionalInteger(values.dimension, 'Dimension'),
    normalize: values.normalize ?? true,
    document_instruction: values.document_instruction ?? '',
    query_instruction: values.query_instruction ?? '',
    enabled: values.enabled ?? true,
    notes: values.notes ?? '',
  };
}

function buildKnowledgeBasePayload(values: Partial<KnowledgeBase>): KnowledgeBaseInput {
  return {
    name: values.name ?? '',
    description: values.description ?? '',
    aliases_text: values.aliases_text ?? '',
    embedding_model_profile_id: values.embedding_model_profile_id ?? '',
    enabled: values.enabled ?? true,
    chunk_size_override: parseOptionalInteger(values.chunk_size_override, 'Chunk size override'),
    chunk_overlap_override: parseOptionalInteger(values.chunk_overlap_override, 'Chunk overlap override'),
    vector_candidate_k_override: parseOptionalInteger(values.vector_candidate_k_override, 'Vector candidate K override'),
    keyword_candidate_k_override: parseOptionalInteger(values.keyword_candidate_k_override, 'Keyword candidate K override'),
    final_top_k_override: parseOptionalInteger(values.final_top_k_override, 'Final top K override'),
    max_context_chars_override: parseOptionalInteger(values.max_context_chars_override, 'Max context chars override'),
    default_chunk_profile: values.default_chunk_profile || 'markdown_auto',
  };
}

function parseOptionalInteger(value: number | string | null | undefined, label: string): number | null {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  const numberValue = typeof value === 'number' ? value : Number(value);
  if (!Number.isInteger(numberValue)) {
    throw new Error(`${label} must be a whole number.`);
  }
  return numberValue;
}

function sortSources(sources: KnowledgeSource[], sort: { key: SourceSortKey; direction: SortDirection }): KnowledgeSource[] {
  const direction = sort.direction === 'asc' ? 1 : -1;
  return [...sources].sort((left, right) => {
    const leftValue = sourceSortValue(left, sort.key);
    const rightValue = sourceSortValue(right, sort.key);
    if (typeof leftValue === 'number' && typeof rightValue === 'number') {
      return (leftValue - rightValue) * direction;
    }
    return String(leftValue).localeCompare(String(rightValue)) * direction;
  });
}

function sourceSortValue(source: KnowledgeSource, key: SourceSortKey): string | number {
  if (key === 'chunks') return source.chunks;
  if (key === 'indexed_at') return source.indexed_at ? new Date(source.indexed_at).getTime() : 0;
  if (key === 'folder_path') return String(source.folder_path || '').toLowerCase();
  if (key === 'status') return sourceIndexStatus(source).toLowerCase();
  return String(source[key] || '').toLowerCase();
}

function chunkProfileLabels(t: ReturnType<typeof useTranslation>['t']): Record<string, string> {
  return Object.fromEntries(CHUNK_PROFILES.map((profile) => [profile, chunkProfileLabel(profile, t)]));
}

function chunkProfileLabel(profile: unknown, t: ReturnType<typeof useTranslation>['t']): string {
  const key = String(profile || '');
  return key ? t(`knowledge:chunkProfiles.${key}`, { defaultValue: key }) : t('status:common.unknown', { ns: 'status' });
}

function profileSourceLabel(source: unknown, t: ReturnType<typeof useTranslation>['t']): string {
  const key = String(source || '');
  return key ? t(`knowledge:profileSources.${key}`, { defaultValue: key }) : t('status:common.unknown', { ns: 'status' });
}

function confidenceLabel(value: unknown, t: ReturnType<typeof useTranslation>['t']): string {
  const confidence = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(confidence)) return t('status:common.unknown', { ns: 'status' });
  if (confidence >= 0.8) return t('knowledge:confidence.high');
  if (confidence >= 0.6) return t('knowledge:confidence.medium');
  return t('knowledge:confidence.low');
}

function entityLevelLabel(value: unknown, t: ReturnType<typeof useTranslation>['t']): string {
  const level = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(level) || level <= 0) return t('status:common.none', { ns: 'status' });
  return t('knowledge:labels.headingLevel', { level });
}

function sourceProfileText(source: KnowledgeSource, t: ReturnType<typeof useTranslation>['t']): string {
  const requested = source.chunk_profile_requested || String(source.metadata?.chunk_profile_requested || '');
  const effective = source.chunk_profile_effective || String(source.metadata?.chunk_profile_effective || '');
  if (requested === 'markdown_auto' && effective) {
    return t('knowledge:labels.autoToProfile', { profile: chunkProfileLabel(effective, t) });
  }
  return chunkProfileLabel(effective || requested, t);
}

function sourceListTitle(source: KnowledgeSource, t?: ReturnType<typeof useTranslation>['t']): string {
  const rawTitle = cleanSourceText(source.title) || cleanSourceText(source.metadata?.display_title) || cleanSourceText(source.metadata?.source_display_title);
  const fileName = cleanSourceText(source.file_name);
  const relativePath = cleanSourceText(source.relative_path);
  const fallback = fileStem(fileName) || fileName || relativePath || shortSourceId(source.id);
  if (source.source_type === 'pasted_text') {
    return rawTitle || t?.('knowledge:defaults.pastedTextTitle') || shortSourceId(source.id);
  }
  if (source.source_type === 'attachment_text') {
    return rawTitle || t?.('knowledge:defaults.attachmentTextTitle') || shortSourceId(source.id);
  }
  if (source.source_type === 'origin_file') {
    const metadataTitle = cleanSourceText(source.metadata?.chunk_title) || cleanSourceText(source.metadata?.document_title);
    return rawTitle || metadataTitle || fallback;
  }
  return rawTitle || fileStem(source.file_name || source.relative_path || source.virtual_path || source.uri) || fallback;
}

function sourceListSubtitle(source: KnowledgeSource): string {
  if (source.source_type === 'pasted_text' || source.source_type === 'attachment_text') {
    return '';
  }
  const compactPath = source.source_type === 'origin_file' ? compactOriginSourcePath(source) : compactSourcePath(source);
  const title = sourceListTitle(source);
  const fallback = source.file_name || source.relative_path || source.uri || '';
  if (compactPath && compactPath !== title) return compactPath;
  return fallback && fallback !== title ? fallback : '';
}

function compactSourcePath(source: KnowledgeSource): string {
  const path = source.virtual_path || source.relative_path || source.file_name || source.uri || '';
  const normalized = path.replace(/\\/g, '/').replace(/^data\/knowledge\/origins\/[^/]+\//, '');
  const parts = normalized.split('/').filter(Boolean);
  return parts.length > 2 ? parts.slice(-2).join('/') : normalized;
}

function compactOriginSourcePath(source: KnowledgeSource): string {
  const path = source.relative_path || source.file_name || source.virtual_path || source.uri || '';
  return path.replace(/\\/g, '/').replace(/^data\/knowledge\/origins\/[^/]+\//, '');
}

function sourceIndexStatus(source: KnowledgeSource): string {
  const dynamicSource = source as KnowledgeSource & { indexed_status?: string | null; index_status?: string | null; needs_reindex?: boolean | null };
  if (dynamicSource.needs_reindex) return 'needs_reindex';
  const status = cleanSourceText(dynamicSource.indexed_status) || cleanSourceText(dynamicSource.index_status) || cleanSourceText(source.file_status) || cleanSourceText(source.status);
  return status === 'indexed' ? 'ready' : status || 'pending';
}

function cleanSourceText(value: unknown): string {
  return String(value || '').trim();
}

function fileStem(value: unknown): string {
  const text = cleanSourceText(value).replace(/\\/g, '/');
  const name = text.split('/').filter(Boolean).pop() || text;
  return name.replace(/\.[^.]+$/, '');
}

function shortSourceId(value: string): string {
  return value ? value.slice(0, 8) : '';
}

function profileReasonText(metadata: Record<string, unknown>, t: ReturnType<typeof useTranslation>['t']): string {
  const requested = String(metadata.chunk_profile_requested || '');
  const effective = String(metadata.chunk_profile_effective || '');
  const source = profileSourceLabel(metadata.profile_source, t);
  const confidence = confidenceLabel(metadata.chunk_profile_confidence, t);
  const entityLevel = entityLevelLabel(metadata.entity_level, t);
  if (requested === 'markdown_auto' && effective) {
    return t('knowledge:labels.profileReasonAuto', { profile: chunkProfileLabel(effective, t), source, confidence, entityLevel });
  }
  return t('knowledge:labels.profileReason', { profile: chunkProfileLabel(effective || requested, t), source, confidence, entityLevel });
}

function formatDate(value?: string | null, fallback = ''): string {
  return value ? new Date(value).toLocaleString() : fallback;
}

function formatBytes(value?: number | null): string {
  if (!value) return '0 B';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function isSupportedTextFile(file: File): boolean {
  const extension = fileExtension(file.name);
  const mimeType = file.type.trim().toLowerCase();
  return TEXT_ATTACHMENT_EXTENSIONS.includes(extension) || mimeType.startsWith('text/') || TEXT_ATTACHMENT_MIME_TYPES.includes(mimeType);
}

function fileExtension(name: string): string {
  const match = name.toLowerCase().match(/(\.[^.]+)$/);
  return match ? match[1] : '';
}

const TEXT_ATTACHMENT_EXTENSIONS = ['.txt', '.md', '.py', '.js', '.ts', '.tsx', '.jsx', '.json', '.yaml', '.yml', '.toml', '.xml', '.html', '.css', '.env', '.log', '.csv', '.sql', '.sh', '.ps1', '.bat', '.ini', '.cfg'];
const TEXT_ATTACHMENT_MIME_TYPES = ['application/json', 'application/xml', 'application/yaml', 'application/x-yaml', 'application/toml', 'application/sql'];
const TEXT_ATTACHMENT_ACCEPT = [...TEXT_ATTACHMENT_EXTENSIONS, 'text/*', ...TEXT_ATTACHMENT_MIME_TYPES].join(',');

function Empty({ title, message }: { title: string; message: string }) {
  return <div className="settings-placeholder"><h2>{title}</h2><p>{message}</p></div>;
}

function profileInitials(value: string): string {
  return value
    .replace(/[/_-]/g, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase())
    .join('');
}
