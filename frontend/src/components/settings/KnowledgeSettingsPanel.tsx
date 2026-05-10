import { BrainCircuit, Play, RefreshCw, Save, Search, Trash2 } from 'lucide-react';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client';
import type { EmbeddingModelProfile, EmbeddingModelProfileInput, KnowledgeBase, KnowledgeBaseInput, KnowledgeModelScan, KnowledgeSearchResponse, KnowledgeSettings, KnowledgeSource } from '../../types';
import { DetailTabs } from './DetailTabs';
import type { KnowledgeSettingsCategory } from './SettingsObjectList';
import { SettingsApiError, toSettingsError, type SettingsErrorValue } from './SettingsApiError';
import { ToggleSwitch } from './ToggleSwitch';

type FormMode = 'list' | 'new' | string;

const defaultEmbeddingProfile: Partial<EmbeddingModelProfile> = {
  name: '',
  alias: '',
  model_path: 'embeddings/',
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
  embedding_model_profile_id: '',
  enabled: true,
  chunk_size_override: null,
  chunk_overlap_override: null,
  vector_candidate_k_override: null,
  keyword_candidate_k_override: null,
  final_top_k_override: null,
  max_context_chars_override: null,
};

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
  const [settings, setSettings] = useState<KnowledgeSettings | null>(null);
  const [values, setValues] = useState<KnowledgeSettings | null>(null);
  const [scan, setScan] = useState<KnowledgeModelScan | null>(null);
  const [embeddingProfiles, setEmbeddingProfiles] = useState<EmbeddingModelProfile[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [busy, setBusy] = useState('');
  const [result, setResult] = useState('');
  const [localError, setLocalError] = useState<SettingsErrorValue | null>(null);
  const dirty = Boolean(values && settings && JSON.stringify(values) !== JSON.stringify(settings));

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
    void refresh().catch((error) => setLocalError(toSettingsError(error, 'Failed to load Knowledge settings.')));
  }, []);

  useEffect(() => {
    onDirtyChange(category === 'defaults' ? dirty : false);
  }, [category, dirty, onDirtyChange]);

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

  async function saveDefaults(event: FormEvent) {
    event.preventDefault();
    if (!values) return;
    setBusy('save');
    try {
      setLocalError(null);
      const saved = await api.updateKnowledgeSettings(knowledgeSettingsPatch(values));
      setSettings(saved);
      setValues(saved);
      setResult('Defaults saved.');
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to save Knowledge defaults.'));
    } finally {
      setBusy('');
    }
  }

  if (!values) {
    return <Empty title="Knowledge" message="Loading Knowledge settings." />;
  }

  if (category === 'embedding_models') {
    return (
      <EmbeddingModelsEditor
        profiles={embeddingProfiles}
        mode={selectedItemId}
        busy={busy}
        result={result}
        error={localError}
        onRefresh={refreshObjects}
        setBusy={setBusy}
        setResult={setResult}
        setLocalError={setLocalError}
      />
    );
  }

  if (category === 'knowledge_bases') {
    return (
      <KnowledgeBasesEditor
        knowledgeBases={knowledgeBases}
        profiles={embeddingProfiles}
        mode={selectedItemId}
        busy={busy}
        result={result}
        error={localError}
        onRefresh={refreshObjects}
        setBusy={setBusy}
        setResult={setResult}
        setLocalError={setLocalError}
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
            <h2>Knowledge Defaults</h2>
            <p>Local model, retrieval, chunking, and context prompt defaults.</p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {result ? <span className="settings-badge success">{result}</span> : null}
          {dirty ? (
            <button className="settings-primary-button" type="submit" disabled={busy === 'save'}>
              <Save size={14} />
              {busy === 'save' ? 'Saving...' : 'Save'}
            </button>
          ) : null}
        </div>
      </header>
      <div className="settings-detail-body">
        {localError ? <SettingsApiError error={localError} /> : null}
        <div className="detail-section">
          <div className="detail-section-heading">
            <h3>Local Models</h3>
          </div>
          <dl className="settings-definition-grid">
            <Metric label="Models root" value={values.models_root} />
            <Metric label="Backend" value={backendLabel(scan?.backend)} />
          </dl>
          <div className="settings-detail-grid">
            <SelectField label="Local model device" value={values.local_model_device} options={['auto', 'cpu', 'cuda']} onChange={(value) => setValues({ ...values, local_model_device: value as KnowledgeSettings['local_model_device'] })} />
          </div>
          <div className="settings-button-row">
            <button className="settings-secondary-button" type="button" onClick={runScan} disabled={busy === 'scan'}>
              <RefreshCw size={14} />
              {busy === 'scan' ? 'Scanning...' : 'Scan local models'}
            </button>
          </div>
          {scan ? <ModelScanSummary scan={scan} /> : null}
        </div>
        <NumberGroup title="Embedding" values={values} setValues={setValues} fields={[['embedding_batch_size', 'Batch size'], ['embedding_timeout_seconds', 'Timeout seconds']]} />
        <div className="detail-section">
          <div className="detail-section-heading"><h3>Reranker</h3></div>
          <label className="config-field settings-config-field boolean-field">
            <span>Enabled</span>
            <ToggleSwitch checked={values.reranker_enabled} onChange={(checked) => setValues({ ...values, reranker_enabled: checked })} />
          </label>
          <div className="settings-detail-grid">
            <TextField label="Reranker model path" value={values.reranker_model_path || ''} onChange={(value) => setValues({ ...values, reranker_model_path: value || null })} />
            <NumberField label="Batch size" value={values.reranker_batch_size} onChange={(value) => { if (value !== '') setValues({ ...values, reranker_batch_size: value }); }} />
            <NumberField label="Timeout seconds" value={values.reranker_timeout_seconds} onChange={(value) => { if (value !== '') setValues({ ...values, reranker_timeout_seconds: value }); }} />
            <NumberField label="Candidate limit" value={values.reranker_candidate_limit} onChange={(value) => { if (value !== '') setValues({ ...values, reranker_candidate_limit: value }); }} />
          </div>
          <div className="settings-button-row">
            <button className="settings-secondary-button" type="button" onClick={async () => {
              setBusy('rerank');
              try {
                setLocalError(null);
                const response = await api.rerankKnowledge({ query: 'What is RAG?', documents: [{ id: 'doc1', text: 'Retrieval augmented generation uses retrieved context.' }, { id: 'doc2', text: 'Other text.' }] });
                setResult(`Reranker test returned ${response.results.length} results.`);
              } catch (error) {
                setLocalError(toSettingsError(error, 'Reranker unavailable.'));
              } finally {
                setBusy('');
              }
            }}>
              <Play size={14} />
              Test reranker
            </button>
          </div>
        </div>
        <NumberGroup title="Retrieval" values={values} setValues={setValues} fields={[['default_vector_candidate_k', 'Vector candidate K'], ['default_keyword_candidate_k', 'Keyword candidate K'], ['default_final_top_k', 'Final top K'], ['default_max_context_chars', 'Max context chars'], ['rrf_k', 'RRF K']]} />
        <div className="detail-section">
          <div className="detail-section-heading"><h3>Retrieval switches</h3></div>
          <label className="config-field settings-config-field boolean-field">
            <span>Hybrid search enabled</span>
            <ToggleSwitch checked={values.hybrid_search_enabled} onChange={(checked) => setValues({ ...values, hybrid_search_enabled: checked })} />
          </label>
          <div className="settings-detail-grid">
            <NumberField label="Min score" value={values.default_min_score ?? ''} onChange={(value) => setValues({ ...values, default_min_score: value === '' ? null : Number(value) })} />
          </div>
        </div>
        <NumberGroup title="Chunking" values={values} setValues={setValues} fields={[['default_chunk_size', 'Chunk size'], ['default_chunk_overlap', 'Chunk overlap']]} />
        <NumberGroup title="Index limits" values={values} setValues={setValues} fields={[['max_source_size_bytes', 'Max source size bytes'], ['max_chunks_per_source', 'Max chunks per source'], ['max_total_index_chars_per_source', 'Max total index chars per source']]} />
        <div className="detail-section">
          <div className="detail-section-heading"><h3>Context Injection</h3></div>
          <TextAreaField label="Knowledge context instruction" value={values.knowledge_context_instruction} onChange={(value) => setValues({ ...values, knowledge_context_instruction: value })} />
          <TextAreaField label="Snippet template" value={values.knowledge_context_snippet_template} onChange={(value) => setValues({ ...values, knowledge_context_snippet_template: value })} />
        </div>
      </div>
    </form>
  );
}

function EmbeddingModelsEditor({ profiles, mode, busy, result, error, onRefresh, setBusy, setResult, setLocalError }: {
  profiles: EmbeddingModelProfile[];
  mode: FormMode;
  busy: string;
  result: string;
  error: SettingsErrorValue | null;
  onRefresh: (selectedItemId?: string) => Promise<void>;
  setBusy: (value: string) => void;
  setResult: (value: string) => void;
  setLocalError: (value: SettingsErrorValue | null) => void;
}) {
  const selected = profiles.find((profile) => profile.id === mode);
  const initial = mode === 'new' ? defaultEmbeddingProfile : selected;
  if (!initial) {
    return <Empty title="No embedding model selected" message={profiles.length ? 'Select an embedding model profile from the list.' : 'No embedding model profiles yet.'} />;
  }
  return <EmbeddingProfileForm initial={initial} isNew={mode === 'new'} busy={busy} result={result} error={error} onRefresh={onRefresh} setBusy={setBusy} setResult={setResult} setLocalError={setLocalError} />;
}

function EmbeddingProfileForm({ initial, isNew, busy, result, error, onRefresh, setBusy, setResult, setLocalError }: {
  initial: Partial<EmbeddingModelProfile>;
  isNew: boolean;
  busy: string;
  result: string;
  error: SettingsErrorValue | null;
  onRefresh: (selectedItemId?: string) => Promise<void>;
  setBusy: (value: string) => void;
  setResult: (value: string) => void;
  setLocalError: (value: SettingsErrorValue | null) => void;
}) {
  const [values, setValues] = useState<Partial<EmbeddingModelProfile>>(initial);

  useEffect(() => {
    setValues(initial);
  }, [initial]);

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy('saving');
    try {
      setLocalError(null);
      const payload = buildEmbeddingModelPayload(values);
      const saved = isNew ? await api.createEmbeddingModel(payload) : await api.patchEmbeddingModel(values.id || '', payload);
      await onRefresh(saved.id);
      setResult('Embedding model saved.');
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to save embedding model.'));
    } finally {
      setBusy('');
    }
  }
  async function remove() {
    if (!values.id) return;
    setBusy('deleting');
    try {
      setLocalError(null);
      await api.deleteEmbeddingModel(values.id);
      await onRefresh();
      setResult('Embedding model deleted.');
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to delete embedding model.'));
    } finally {
      setBusy('');
    }
  }
  async function test() {
    if (!values.id) return;
    setBusy('testing');
    try {
      setLocalError(null);
      const response = await api.testEmbeddingModel(values.id, 'hello world', 'query');
      setResult(`Embedding dimension ${response.dimension}.`);
    } catch (error) {
      setLocalError(toSettingsError(error, 'Embedding backend unavailable.'));
    } finally {
      setBusy('');
    }
  }
  return (
    <form className="settings-detail-form" onSubmit={save}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">{profileInitials(values.name || values.alias || 'EM') || <BrainCircuit size={18} />}</div>
          <div>
            <h2>{values.name || 'New embedding model'}</h2>
            <p>
              <code>{values.alias || 'profile_key'}</code>
              <span>{values.model_path || 'No model path'}</span>
            </p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {result ? <span className="settings-badge success">{result}</span> : null}
          <button className="settings-primary-button" type="submit" disabled={Boolean(busy)}>
            <Save size={14} />
            {busy === 'saving' ? 'Saving...' : 'Save'}
          </button>
          {!isNew ? <button className="settings-secondary-button" type="button" onClick={test} disabled={Boolean(busy)}><Play size={14} />{busy === 'testing' ? 'Testing...' : 'Test'}</button> : null}
          {!isNew ? <button className="settings-secondary-button danger" type="button" onClick={remove} disabled={Boolean(busy)}><Trash2 size={14} />Delete</button> : null}
          <ToggleSwitch checked={values.enabled ?? true} onChange={(checked) => setValues({ ...values, enabled: checked })} disabled={Boolean(busy)} />
        </div>
      </header>
      <div className="settings-detail-body">
        {error ? <SettingsApiError error={error} /> : null}
        <section className="detail-section">
          <h3>Model</h3>
          <div className="settings-detail-grid">
            <TextField label="Name" value={values.name || ''} onChange={(value) => setValues({ ...values, name: value })} />
            <TextField label="Profile key" value={values.alias || ''} onChange={(value) => setValues({ ...values, alias: value })} />
            <TextField label="Model path" value={values.model_path || ''} onChange={(value) => setValues({ ...values, model_path: value })} />
            <NumberField label="Dimension" value={values.dimension ?? ''} onChange={(value) => setValues({ ...values, dimension: value === '' ? null : Number(value) })} />
          </div>
        </section>
        <section className="detail-section">
          <h3>Runtime</h3>
          <label className="config-field settings-config-field boolean-field"><span>Normalize</span><ToggleSwitch checked={values.normalize ?? true} onChange={(checked) => setValues({ ...values, normalize: checked })} /></label>
          <TextAreaField label="Document instruction" value={values.document_instruction || ''} onChange={(value) => setValues({ ...values, document_instruction: value })} />
          <TextAreaField label="Query instruction" value={values.query_instruction || ''} onChange={(value) => setValues({ ...values, query_instruction: value })} />
          <TextAreaField label="Notes" value={values.notes || ''} onChange={(value) => setValues({ ...values, notes: value })} />
        </section>
      </div>
    </form>
  );
}

function KnowledgeBasesEditor({ knowledgeBases, profiles, mode, busy, result, error, onRefresh, setBusy, setResult, setLocalError }: {
  knowledgeBases: KnowledgeBase[];
  profiles: EmbeddingModelProfile[];
  mode: FormMode;
  busy: string;
  result: string;
  error: SettingsErrorValue | null;
  onRefresh: (selectedItemId?: string) => Promise<void>;
  setBusy: (value: string) => void;
  setResult: (value: string) => void;
  setLocalError: (value: SettingsErrorValue | null) => void;
}) {
  const selected = knowledgeBases.find((kb) => kb.id === mode);
  const initial = useMemo(() => mode === 'new' ? { ...defaultKnowledgeBase, embedding_model_profile_id: profiles[0]?.id || '' } : selected, [mode, profiles, selected]);
  if (!initial) {
    return <Empty title="No knowledge base selected" message={knowledgeBases.length ? 'Select a knowledge base from the list.' : 'No knowledge bases yet.'} />;
  }
  return <KnowledgeBaseForm initial={initial} profiles={profiles} isNew={mode === 'new'} busy={busy} result={result} error={error} onRefresh={onRefresh} setBusy={setBusy} setResult={setResult} setLocalError={setLocalError} />;
}

function KnowledgeBaseForm({ initial, profiles, isNew, busy, result, error, onRefresh, setBusy, setResult, setLocalError }: {
  initial: Partial<KnowledgeBase>;
  profiles: EmbeddingModelProfile[];
  isNew: boolean;
  busy: string;
  result: string;
  error: SettingsErrorValue | null;
  onRefresh: (selectedItemId?: string) => Promise<void>;
  setBusy: (value: string) => void;
  setResult: (value: string) => void;
  setLocalError: (value: SettingsErrorValue | null) => void;
}) {
  const [values, setValues] = useState<Partial<KnowledgeBase>>(initial);
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [sourceTitle, setSourceTitle] = useState('');
  const [sourceText, setSourceText] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResponse, setSearchResponse] = useState<KnowledgeSearchResponse | null>(null);
  const [activeTab, setActiveTab] = useState<'config' | 'sources'>('config');
  const selectedProfile = profiles.find((profile) => profile.id === values.embedding_model_profile_id);

  useEffect(() => {
    setValues(initial);
  }, [initial]);

  useEffect(() => {
    setActiveTab('config');
  }, [initial.id, isNew]);

  useEffect(() => {
    if (!initial.id || isNew) {
      setSources([]);
      return;
    }
    void loadSources(initial.id);
  }, [initial.id, isNew]);

  async function loadSources(knowledgeBaseId = values.id || '') {
    if (!knowledgeBaseId) return;
    try {
      setSources(await api.listKnowledgeSources(knowledgeBaseId));
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to load knowledge sources.'));
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy('saving');
    try {
      setLocalError(null);
      const payload = buildKnowledgeBasePayload(values);
      const saved = isNew ? await api.createKnowledgeBase(payload) : await api.patchKnowledgeBase(values.id || '', payload);
      await onRefresh(saved.id);
      setResult('Knowledge base saved.');
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to save knowledge base.'));
    } finally {
      setBusy('');
    }
  }
  async function remove() {
    if (!values.id) return;
    setBusy('deleting');
    try {
      setLocalError(null);
      await api.deleteKnowledgeBase(values.id);
      await onRefresh();
      setResult('Knowledge base deleted.');
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to delete knowledge base.'));
    } finally {
      setBusy('');
    }
  }
  async function addPastedSource() {
    if (!values.id || !sourceText.trim()) return;
    setBusy('indexing');
    try {
      setLocalError(null);
      const indexed = await api.createPastedKnowledgeSource(values.id, { title: sourceTitle || 'Pasted text', text: sourceText });
      setSourceTitle('');
      setSourceText('');
      await loadSources(values.id);
      await onRefresh(values.id);
      setResult(`Indexed ${indexed.chunks} chunks.`);
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to index pasted text source.'));
    } finally {
      setBusy('');
    }
  }
  async function deleteSource(sourceId: string) {
    if (!values.id) return;
    setBusy('deleting source');
    try {
      setLocalError(null);
      await api.deleteKnowledgeSource(sourceId);
      await loadSources(values.id);
      await onRefresh(values.id);
      setResult('Source deleted.');
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to delete source.'));
    } finally {
      setBusy('');
    }
  }
  async function reindexSource(sourceId: string) {
    if (!values.id) return;
    setBusy('reindexing');
    try {
      setLocalError(null);
      const result = await api.reindexKnowledgeSource(sourceId);
      await loadSources(values.id);
      await onRefresh(values.id);
      setResult(`Reindexed ${result.chunks} chunks.`);
    } catch (error) {
      setLocalError(toSettingsError(error, 'Failed to reindex source.'));
    } finally {
      setBusy('');
    }
  }
  async function runSearch() {
    if (!values.id || !searchQuery.trim()) return;
    setBusy('searching');
    try {
      setLocalError(null);
      setSearchResponse(await api.searchKnowledge({ query: searchQuery, knowledge_base_ids: [values.id], debug: true }));
    } catch (error) {
      setLocalError(toSettingsError(error, 'Knowledge search failed.'));
    } finally {
      setBusy('');
    }
  }
  return (
    <form className="settings-detail-form" onSubmit={save}>
      <header className="settings-detail-header">
        <div className="settings-detail-title">
          <div className="settings-detail-avatar">{profileInitials(values.name || 'KB') || <BrainCircuit size={18} />}</div>
          <div>
            <h2>{values.name || 'New knowledge base'}</h2>
            <p>
              <span>Knowledge base configuration, sources, and local indexes.</span>
              <span>{'index_status' in values ? values.index_status || 'empty' : 'unsaved'}</span>
              <span>{selectedProfile?.alias || 'missing model'}</span>
            </p>
          </div>
        </div>
        <div className="settings-detail-actions">
          {result ? <span className="settings-badge success">{result}</span> : null}
          <button className="settings-primary-button" type="submit" disabled={Boolean(busy)}>
            <Save size={14} />
            {busy === 'saving' ? 'Saving...' : 'Save'}
          </button>
          {!isNew ? <button className="settings-secondary-button danger" type="button" onClick={remove} disabled={Boolean(busy)}><Trash2 size={14} />Delete</button> : null}
          <ToggleSwitch checked={values.enabled ?? true} onChange={(checked) => setValues({ ...values, enabled: checked })} disabled={Boolean(busy)} />
        </div>
      </header>
      <DetailTabs tabs={[{ id: 'config', label: 'Config' }, { id: 'sources', label: 'Sources', enabled: !isNew && Boolean(values.id) }]} activeTab={activeTab} onChange={(tab) => setActiveTab(tab as 'config' | 'sources')} />
      <div className="settings-detail-body">
        {error ? <SettingsApiError error={error} /> : null}
        {activeTab === 'config' ? (
          <>
            <section className="detail-section">
              <h3>Config</h3>
              <div className="settings-detail-grid">
                <TextField label="Name" value={values.name || ''} onChange={(value) => setValues({ ...values, name: value })} />
                <SelectField label="Embedding model profile" value={values.embedding_model_profile_id || ''} options={profiles.map((profile) => profile.id)} labels={Object.fromEntries(profiles.map((profile) => [profile.id, profile.alias]))} onChange={(value) => setValues({ ...values, embedding_model_profile_id: value })} />
              </div>
              <TextAreaField label="Description" value={values.description || ''} onChange={(value) => setValues({ ...values, description: value })} />
              {'index_status' in values ? <dl className="settings-definition-grid"><Metric label="Index status" value={values.index_status || 'empty'} /></dl> : null}
            </section>
            <section className="detail-section">
              <h3>Overrides</h3>
              <div className="settings-detail-grid">
                <NumberField label="Chunk size override" value={values.chunk_size_override ?? ''} onChange={(value) => setValues({ ...values, chunk_size_override: value === '' ? null : Number(value) })} />
                <NumberField label="Chunk overlap override" value={values.chunk_overlap_override ?? ''} onChange={(value) => setValues({ ...values, chunk_overlap_override: value === '' ? null : Number(value) })} />
                <NumberField label="Vector candidate K override" value={values.vector_candidate_k_override ?? ''} onChange={(value) => setValues({ ...values, vector_candidate_k_override: value === '' ? null : Number(value) })} />
                <NumberField label="Keyword candidate K override" value={values.keyword_candidate_k_override ?? ''} onChange={(value) => setValues({ ...values, keyword_candidate_k_override: value === '' ? null : Number(value) })} />
                <NumberField label="Final top K override" value={values.final_top_k_override ?? ''} onChange={(value) => setValues({ ...values, final_top_k_override: value === '' ? null : Number(value) })} />
                <NumberField label="Max context chars override" value={values.max_context_chars_override ?? ''} onChange={(value) => setValues({ ...values, max_context_chars_override: value === '' ? null : Number(value) })} />
              </div>
            </section>
          </>
        ) : null}
        {activeTab === 'sources' && !isNew && values.id ? (
          <>
            <section className="detail-section">
              <div className="detail-section-heading"><h3>Sources</h3></div>
              {sources.length ? (
                <div className="settings-object-table">
                  {sources.map((source) => (
                    <div className="settings-object-row" key={source.id}>
                      <div>
                        <strong>{source.title}</strong>
                        <p>{source.source_type} / {source.status} / {source.chunks} chunks{source.indexed_at ? ` / ${new Date(source.indexed_at).toLocaleString()}` : ''}</p>
                        {source.error ? <p className="settings-error-text">{source.error}</p> : null}
                      </div>
                      <div className="settings-button-row compact">
                        <button className="settings-secondary-button" type="button" onClick={() => reindexSource(source.id)} disabled={Boolean(busy)}><RefreshCw size={14} />Reindex</button>
                        <button className="settings-secondary-button danger" type="button" onClick={() => deleteSource(source.id)} disabled={Boolean(busy)}><Trash2 size={14} />Delete</button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : <Empty title="No sources" message="No sources have been indexed for this knowledge base." />}
              <div className="settings-detail-grid">
                <TextField label="Pasted source title" value={sourceTitle} onChange={setSourceTitle} />
              </div>
              <TextAreaField label="Pasted text" value={sourceText} onChange={setSourceText} />
              <div className="settings-button-row">
                <button className="settings-secondary-button" type="button" disabled={!sourceText.trim() || Boolean(busy)} onClick={addPastedSource}><Play size={14} />Index pasted text</button>
              </div>
            </section>
            <section className="detail-section">
              <div className="detail-section-heading"><h3>Search Test</h3></div>
              <div className="settings-detail-grid">
                <TextField label="Query" value={searchQuery} onChange={setSearchQuery} />
              </div>
              <div className="settings-button-row">
                <button className="settings-secondary-button" type="button" disabled={!searchQuery.trim() || Boolean(busy)} onClick={runSearch}><Search size={14} />Search</button>
              </div>
              {searchResponse ? <KnowledgeSearchResults response={searchResponse} /> : null}
            </section>
          </>
        ) : null}
        {activeTab === 'sources' && (isNew || !values.id) ? <Empty title="Save first" message="Save this knowledge base before adding sources." /> : null}
      </div>
    </form>
  );
}

function KnowledgeSearchResults({ response }: { response: KnowledgeSearchResponse }) {
  return (
    <div className="settings-object-table">
      {response.results.length ? response.results.map((result) => (
        <div className="settings-object-row" key={result.chunk_id}>
          <div>
            <strong>#{result.rank} {result.title || result.source_id}</strong>
            <p>{result.content}{result.truncated ? '...' : ''}</p>
            <p className="settings-muted-text">
              vector {scoreLabel(result.vector_score)} / keyword {scoreLabel(result.keyword_score)} / rrf {scoreLabel(result.rrf_score)} / rerank {scoreLabel(result.rerank_score)}
            </p>
          </div>
        </div>
      )) : <Empty title="No results" message="No chunks matched this query." />}
      {response.debug ? (
        <details className="settings-debug-details">
          <summary>Debug</summary>
          <pre>{JSON.stringify(response.debug, null, 2)}</pre>
        </details>
      ) : null}
    </div>
  );
}

function scoreLabel(value?: number | null): string {
  return typeof value === 'number' ? value.toFixed(4) : 'n/a';
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

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label className="config-field settings-config-field"><span>{label}</span><input className="settings-form-control" type="text" value={value} onChange={(event) => onChange(event.currentTarget.value)} /></label>;
}

function NumberField({ label, value, onChange }: { label: string; value: number | string; onChange: (value: number | '') => void }) {
  return <label className="config-field settings-config-field"><span>{label}</span><input className="settings-form-control" type="number" value={value} onChange={(event) => onChange(event.currentTarget.value === '' ? '' : Number(event.currentTarget.value))} /></label>;
}

function TextAreaField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label className="config-field settings-config-field"><span>{label}</span><textarea className="settings-form-control" rows={6} value={value} onChange={(event) => onChange(event.currentTarget.value)} /></label>;
}

function SelectField({ label, value, options, labels, onChange }: { label: string; value: string; options: string[]; labels?: Record<string, string>; onChange: (value: string) => void }) {
  return <label className="config-field settings-config-field"><span>{label}</span><select className="settings-form-control" value={value} onChange={(event) => onChange(event.currentTarget.value)}>{options.map((option) => <option key={option} value={option}>{labels?.[option] || option}</option>)}</select></label>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd title={value}>{value}</dd></div>;
}

function ModelScanSummary({ scan }: { scan: KnowledgeModelScan }) {
  return (
    <dl className="settings-definition-grid">
      <Metric label="Embedding folders" value={String(scan.embedding_models.length)} />
      <Metric label="Reranker folders" value={String(scan.reranker_models.length)} />
      <Metric label="sentence-transformers" value={scan.backend.sentence_transformers_available ? 'Available' : 'Unavailable'} />
      <Metric label="torch" value={scan.backend.torch_available ? 'Available' : 'Unavailable'} />
    </dl>
  );
}

function backendLabel(backend?: KnowledgeModelScan['backend']): string {
  if (!backend) return 'Not scanned';
  return backend.available ? 'Available' : 'Unavailable: optional dependencies missing';
}

function knowledgeSettingsPatch(values: KnowledgeSettings): Partial<KnowledgeSettings> {
  const { id, models_root, ...patch } = values;
  void id;
  void models_root;
  return patch;
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
    embedding_model_profile_id: values.embedding_model_profile_id ?? '',
    enabled: values.enabled ?? true,
    chunk_size_override: parseOptionalInteger(values.chunk_size_override, 'Chunk size override'),
    chunk_overlap_override: parseOptionalInteger(values.chunk_overlap_override, 'Chunk overlap override'),
    vector_candidate_k_override: parseOptionalInteger(values.vector_candidate_k_override, 'Vector candidate K override'),
    keyword_candidate_k_override: parseOptionalInteger(values.keyword_candidate_k_override, 'Keyword candidate K override'),
    final_top_k_override: parseOptionalInteger(values.final_top_k_override, 'Final top K override'),
    max_context_chars_override: parseOptionalInteger(values.max_context_chars_override, 'Max context chars override'),
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
