import { ArrowLeft } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useModelsStore } from '../store/useModelsStore';
import { useTranslation } from 'react-i18next';
import { ModelsPanel } from './settings/ModelsPanel';
import { api, ApiError } from '../api/client';
import type { GeneralSettings, KnowledgeBase, KnowledgeSettings, PetSettings, Worldbook, WorldbookSettings } from '../types';
import { PetSettingsPanel } from './settings/PetSettingsPanel';
import { PersonasPanel } from './settings/PersonasPanel';
import { ToolsPanel } from './settings/ToolsPanel';

export type SettingsSection = 'general' | 'models' | 'personas' | 'knowledge' | 'worldbook' | 'tools' | 'pet';

export function SettingsPage({ onBack }: { onBack: () => void }) {
  const { t } = useTranslation('settings');
  const [section, setSection] = useState<SettingsSection>(readSection());
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  function run<T>(task: () => Promise<T>, success = 'Saved') { setError(''); void task().then(() => setMessage(success)).catch((reason) => setError(reason instanceof ApiError ? `${reason.code}: ${reason.message}` : String(reason))); }
  return <div className="settings-page"><header className="settings-header"><button className="icon-button" type="button" onClick={onBack} title={t('common:back')}><ArrowLeft size={18} /></button><div><h1>{t('title')}</h1></div><div className="settings-feedback">{message ? <span className="success-text">{message}</span> : null}{error ? <span className="error-text">{error}</span> : null}</div></header><div className="settings-layout"><nav className="settings-nav" aria-label={t('title')}>{(['general', 'models', 'personas', 'knowledge', 'worldbook', 'tools', 'pet'] as SettingsSection[]).map((item) => <button key={item} type="button" className={section === item ? 'active' : ''} onClick={() => { setSection(item); window.history.replaceState({}, '', `/settings?tab=${item}`); }}>{t(item)}</button>)}</nav><main className="settings-content">{section === 'general' ? <GeneralPanel save={(patch) => run(() => api.updateGeneralSettings(patch).then(() => undefined))} /> : null}{section === 'models' ? <ModelsPanel /> : null}{section === 'personas' ? <PersonasPanel /> : null}{section === 'knowledge' ? <KnowledgePanel save={(task) => run(task)} /> : null}{section === 'worldbook' ? <WorldbookPanel save={(task) => run(task)} /> : null}{section === 'tools' ? <ToolsPanel /> : null}{section === 'pet' ? <PetSettingsPanel /> : null}</main></div></div>;
}

function GeneralPanel({ save }: { save: (patch: Record<string, unknown>) => void }) {
  const [settings, setSettings] = useState<GeneralSettings | null>(null);
  useEffect(() => { void api.getGeneralSettings().then(setSettings).catch(() => undefined); }, []);
  if (!settings) return <Loading />;
  const patch = (key: string, value: unknown) => setSettings({ ...settings, [key]: value });
  return <Panel title="General"><Toggle label="Enable core memory" checked={settings.core_memory_enabled} onChange={(value) => patch('core_memory_enabled', value)} /><TextArea label="Core memory" value={settings.core_memory_content} onChange={(value) => patch('core_memory_content', value)} /><Toggle label="Generate session titles" checked={settings.auto_generate_session_titles} onChange={(value) => patch('auto_generate_session_titles', value)} /><NumberField label="Title input limit" value={settings.session_title_max_input_chars} onChange={(value) => patch('session_title_max_input_chars', value)} /><TextArea label="Group transcript instruction" value={settings.group_transcript_system_instruction || ''} onChange={(value) => patch('group_transcript_system_instruction', value || null)} /><button className="primary-button" type="button" onClick={() => save({ core_memory_enabled: settings.core_memory_enabled, core_memory_content: settings.core_memory_content, auto_generate_session_titles: settings.auto_generate_session_titles, session_title_max_input_chars: settings.session_title_max_input_chars, group_transcript_system_instruction: settings.group_transcript_system_instruction })}>Save general settings</button></Panel>;
}

function KnowledgePanel({ save }: { save: (task: () => Promise<unknown>) => void }) {
  const [settings, setSettings] = useState<KnowledgeSettings | null>(null);
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const { t } = useTranslation('llm');
  const models = useModelsStore((state) => state.profiles);
  const reloadModels = useModelsStore((state) => state.reload);
  const embeddings = models.filter((p) => p.kind === 'embedding' && p.enabled);
  const [newBase, setNewBase] = useState({ name: '', embedding_model_profile_id: '' });
  const reload = () => Promise.all([api.getKnowledgeSettings(), api.listKnowledgeBases(), reloadModels()]).then(([s, b]) => { setSettings(s); setBases(b); });
  useEffect(() => { void reload(); }, []);
  if (!settings) return <Loading />;
  const patch = (key: string, value: unknown) => setSettings({ ...settings, [key]: value } as KnowledgeSettings);
  return <Panel title="Knowledge"><Toggle label="Hybrid vector + keyword search" checked={settings.hybrid_search_enabled} onChange={(value) => patch('hybrid_search_enabled', value)} /><Toggle label="Enable optional reranker" checked={settings.reranker_enabled} onChange={(value) => patch('reranker_enabled', value)} /><label className="settings-field"><span>{t('kinds.reranker')}</span><select value={settings.reranker_model_profile_id || ''} onChange={(e) => patch('reranker_model_profile_id', e.currentTarget.value || null)}><option value="">{t('unconfigured')}</option>{models.filter((p) => p.kind === 'reranker' && p.enabled).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label><NumberField label="Chunk size" value={settings.default_chunk_size} onChange={(value) => patch('default_chunk_size', value)} /><NumberField label="Chunk overlap" value={settings.default_chunk_overlap} onChange={(value) => patch('default_chunk_overlap', value)} /><NumberField label="Final results" value={settings.default_final_top_k} onChange={(value) => patch('default_final_top_k', value)} /><button className="primary-button" type="button" onClick={() => save(() => api.updateKnowledgeSettings(Object.fromEntries(Object.entries(settings).filter(([key]) => key !== "id"))).then(() => undefined))}>Save knowledge settings</button><h3>Knowledge bases</h3><div className="settings-list">{bases.map((base) => <div className="settings-list-row" key={base.id}><span>{base.name}<small>{base.index_status}</small></span><button type="button" onClick={() => save(() => api.deleteKnowledgeBase(base.id).then(() => reload()))}>Delete</button></div>)}</div><div className="inline-form"><input placeholder="Base name" value={newBase.name} onChange={(event) => setNewBase({ ...newBase, name: event.currentTarget.value })} /><select value={newBase.embedding_model_profile_id} onChange={(event) => setNewBase({ ...newBase, embedding_model_profile_id: event.currentTarget.value })}><option value="">Embedding profile</option>{embeddings.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><button className="secondary-button" type="button" disabled={!newBase.name || !newBase.embedding_model_profile_id} onClick={() => save(() => api.createKnowledgeBase(newBase).then(() => { setNewBase({ name: '', embedding_model_profile_id: newBase.embedding_model_profile_id }); return reload(); }))}>Add base</button></div></Panel>;
}

function WorldbookPanel({ save }: { save: (task: () => Promise<unknown>) => void }) {
  const [settings, setSettings] = useState<WorldbookSettings | null>(null);
  const [items, setItems] = useState<Worldbook[]>([]);
  const [name, setName] = useState('');
  const reload = () => Promise.all([api.getWorldbookSettings(), api.listWorldbooks()]).then(([s, w]) => { setSettings(s); setItems(w); });
  useEffect(() => { void reload(); }, []);
  if (!settings) return <Loading />;
  return <Panel title="Worldbook"><Toggle label="Enable worldbook context" checked={settings.worldbook_enabled} onChange={(value) => setSettings({ ...settings, worldbook_enabled: value })} /><NumberField label="Maximum entries" value={settings.worldbook_max_entries_per_call} onChange={(value) => setSettings({ ...settings, worldbook_max_entries_per_call: value })} /><button className="primary-button" type="button" onClick={() => save(() => api.updateWorldbookSettings(settings).then(() => undefined))}>Save worldbook settings</button><h3>Worldbooks</h3><div className="settings-list">{items.map((item) => <div className="settings-list-row" key={item.id}><span>{item.name}<small>{item.entry_count || 0} entries</small></span><button type="button" onClick={() => save(() => api.deleteWorldbook(item.id).then(() => reload()))}>Delete</button></div>)}</div><div className="inline-form"><input placeholder="Worldbook name" value={name} onChange={(event) => setName(event.currentTarget.value)} /><button className="secondary-button" type="button" disabled={!name.trim()} onClick={() => save(() => api.createWorldbook({ name }).then(() => { setName(''); return reload(); }))}>Add worldbook</button></div></Panel>;
}

export function Panel({ title, children }: { title: string; children: React.ReactNode }) { return <section className="settings-panel"><h2>{title}</h2>{children}</section>; }
export function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) { return <label className="settings-toggle"><input type="checkbox" checked={checked} onChange={(event) => onChange(event.currentTarget.checked)} /><span>{label}</span></label>; }
export function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) { return <label className="settings-field"><span>{label}</span><input type="number" value={value} onChange={(event) => onChange(Number(event.currentTarget.value))} /></label>; }
export function TextArea({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <label className="settings-field"><span>{label}</span><textarea value={value} onChange={(event) => onChange(event.currentTarget.value)} rows={4} /></label>; }
function Loading() { return <div className="settings-loading">Loading…</div>; }
function readSection(): SettingsSection { const value = new URLSearchParams(window.location.search).get('tab'); return (['general', 'models', 'personas', 'knowledge', 'worldbook', 'tools', 'pet'] as string[]).includes(value || '') ? value as SettingsSection : 'general'; }
