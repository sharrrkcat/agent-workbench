import { BookOpenText, GripVertical, Pencil, Play, Save, Trash2 } from 'lucide-react';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../api/client';
import type { Worldbook, WorldbookEntry, WorldbookEntryInput, WorldbookInput, WorldbookMatchTestResponse, WorldbookSettings } from '../../types';
import type { WorldbookSettingsCategory } from './SettingsObjectList';
import { DetailTabs } from './DetailTabs';
import { SettingsApiError, toSettingsError, type SettingsErrorValue } from './SettingsApiError';
import { ToggleSwitch } from './ToggleSwitch';

const emptyWorldbook: Partial<Worldbook> = { name: '', description: '', enabled: true };
const emptyEntry: Partial<WorldbookEntry> = { name: '', keywords_text: '', content: '', activation_mode: 'keyword', enabled: true };

export function WorldbookSettingsDetail({
  category,
  selectedItemId = 'global',
  onObjectsChanged,
  onDirtyChange,
}: {
  category: WorldbookSettingsCategory;
  selectedItemId?: string;
  onObjectsChanged?: (selectedItemId?: string) => Promise<void>;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const { t } = useTranslation(['worldbook', 'common']);
  const [settings, setSettings] = useState<WorldbookSettings | null>(null);
  const [values, setValues] = useState<WorldbookSettings | null>(null);
  const [worldbooks, setWorldbooks] = useState<Worldbook[]>([]);
  const [entries, setEntries] = useState<WorldbookEntry[]>([]);
  const [worldbookValues, setWorldbookValues] = useState<Partial<Worldbook>>(emptyWorldbook);
  const [entryValues, setEntryValues] = useState<Partial<WorldbookEntry>>(emptyEntry);
  const [selectedEntryId, setSelectedEntryId] = useState('');
  const [matchText, setMatchText] = useState('');
  const [matchResult, setMatchResult] = useState<WorldbookMatchTestResponse | null>(null);
  const [activeTab, setActiveTab] = useState<'config' | 'entries' | 'match'>('config');
  const [dragEntryId, setDragEntryId] = useState('');
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');
  const [localError, setLocalError] = useState<SettingsErrorValue | null>(null);
  const selectedWorldbook = useMemo(() => worldbooks.find((item) => item.id === selectedItemId), [selectedItemId, worldbooks]);
  const selectedEntry = useMemo(() => entries.find((item) => item.id === selectedEntryId), [entries, selectedEntryId]);
  const defaultsDirty = Boolean(values && settings && JSON.stringify(values) !== JSON.stringify(settings));
  const worldbookDirty = JSON.stringify(worldbookValues) !== JSON.stringify(selectedWorldbook || emptyWorldbook);
  const entryDirty = JSON.stringify(entryValues) !== JSON.stringify(selectedEntry || emptyEntry);

  async function refresh(nextSelectedId?: string) {
    const [nextSettings, nextWorldbooks] = await Promise.all([api.getWorldbookSettings(), api.listWorldbooks()]);
    setSettings(nextSettings);
    setValues(nextSettings);
    setWorldbooks(nextWorldbooks);
    await onObjectsChanged?.(nextSelectedId);
  }

  async function loadEntries(worldbookId: string) {
    if (!worldbookId || worldbookId === 'new') {
      setEntries([]);
      setSelectedEntryId('');
      return;
    }
    const nextEntries = await api.listWorldbookEntries(worldbookId);
    setEntries(nextEntries);
    setSelectedEntryId((current) => current && nextEntries.some((entry) => entry.id === current) ? current : nextEntries[0]?.id || '');
  }

  useEffect(() => {
    void refresh().catch((error) => setLocalError(toSettingsError(error, t('worldbook:errors.loadFailed'))));
  }, []);

  useEffect(() => {
    onDirtyChange(category === 'defaults' ? defaultsDirty : worldbookDirty || entryDirty);
  }, [category, defaultsDirty, worldbookDirty, entryDirty, onDirtyChange]);

  useEffect(() => {
    setLocalError(null);
    setMessage('');
    setMatchResult(null);
    if (category !== 'worldbooks') return;
    setActiveTab('config');
    if (selectedItemId === 'new') {
      setWorldbookValues(emptyWorldbook);
      void loadEntries('');
      return;
    }
    setWorldbookValues(selectedWorldbook || emptyWorldbook);
    void loadEntries(selectedItemId).catch((error) => setLocalError(toSettingsError(error, t('worldbook:errors.loadFailed'))));
  }, [category, selectedItemId, selectedWorldbook]);

  useEffect(() => {
    setEntryValues(selectedEntry || emptyEntry);
  }, [selectedEntry]);

  async function saveDefaults(event: FormEvent) {
    event.preventDefault();
    if (!values) return;
    setBusy('save-defaults');
    try {
      const saved = await api.updateWorldbookSettings(worldbookSettingsPatch(values));
      setSettings(saved);
      setValues(saved);
      setMessage(t('worldbook:results.defaultsSaved'));
    } catch (error) {
      setLocalError(toSettingsError(error, t('worldbook:errors.saveDefaultsFailed')));
    } finally {
      setBusy('');
    }
  }

  async function saveWorldbook(event: FormEvent) {
    event.preventDefault();
    setBusy('save-worldbook');
    try {
      const saved = selectedItemId === 'new'
        ? await api.createWorldbook(worldbookPayload(worldbookValues))
        : await api.patchWorldbook(selectedItemId, worldbookPayload(worldbookValues));
      setMessage(t('worldbook:results.worldbookSaved'));
      await refresh(saved.id);
    } catch (error) {
      setLocalError(toSettingsError(error, t('worldbook:errors.saveWorldbookFailed')));
    } finally {
      setBusy('');
    }
  }

  async function deleteWorldbook() {
    if (!selectedWorldbook) return;
    setBusy('delete-worldbook');
    try {
      await api.deleteWorldbook(selectedWorldbook.id);
      setMessage(t('worldbook:results.worldbookDeleted'));
      await refresh('');
    } catch (error) {
      setLocalError(toSettingsError(error, t('worldbook:errors.deleteWorldbookFailed')));
    } finally {
      setBusy('');
    }
  }

  async function saveEntry(event: FormEvent) {
    event.preventDefault();
    if (!selectedWorldbook) return;
    setBusy('save-entry');
    try {
      const saved = selectedEntryId === 'new'
        ? await api.createWorldbookEntry(selectedWorldbook.id, entryPayload(entryValues))
        : await api.patchWorldbookEntry(selectedEntryId, entryPayload(entryValues));
      setMessage(t('worldbook:results.entrySaved'));
      await loadEntries(selectedWorldbook.id);
      setSelectedEntryId(saved.id);
    } catch (error) {
      setLocalError(toSettingsError(error, t('worldbook:errors.saveEntryFailed')));
    } finally {
      setBusy('');
    }
  }

  async function deleteEntry() {
    if (!selectedEntry || !selectedWorldbook) return;
    setBusy('delete-entry');
    try {
      await api.deleteWorldbookEntry(selectedEntry.id);
      setMessage(t('worldbook:results.entryDeleted'));
      await loadEntries(selectedWorldbook.id);
    } catch (error) {
      setLocalError(toSettingsError(error, t('worldbook:errors.deleteEntryFailed')));
    } finally {
      setBusy('');
    }
  }

  async function reorderEntries(nextEntries: WorldbookEntry[]) {
    if (!selectedWorldbook) return;
    const previousEntries = entries;
    setEntries(nextEntries);
    setBusy('reorder');
    try {
      const response = await api.reorderWorldbookEntries(selectedWorldbook.id, nextEntries.map((entry) => entry.id));
      setEntries(response.entries);
      setMessage(t('worldbook:results.entriesReordered'));
    } catch (error) {
      setEntries(previousEntries);
      setLocalError(toSettingsError(error, t('worldbook:errors.reorderFailed')));
    } finally {
      setBusy('');
      setDragEntryId('');
    }
  }

  function handleEntryDrop(targetEntryId: string) {
    if (!dragEntryId || dragEntryId === targetEntryId || busy) return;
    const sourceIndex = entries.findIndex((entry) => entry.id === dragEntryId);
    const targetIndex = entries.findIndex((entry) => entry.id === targetEntryId);
    if (sourceIndex < 0 || targetIndex < 0) return;
    const nextEntries = [...entries];
    const [moved] = nextEntries.splice(sourceIndex, 1);
    nextEntries.splice(targetIndex, 0, moved);
    void reorderEntries(nextEntries);
  }

  async function runMatchTest() {
    if (!selectedWorldbook) return;
    setBusy('match');
    try {
      setMatchResult(await api.matchWorldbooks({ text: matchText, worldbook_ids: [selectedWorldbook.id] }));
    } catch (error) {
      setLocalError(toSettingsError(error, t('worldbook:errors.matchFailed')));
    } finally {
      setBusy('');
    }
  }

  if (category === 'defaults') {
    if (!values) return <Empty title={t('worldbook:titles.defaults')} message={t('worldbook:empty.loadingSettings')} />;
    return (
      <form className="settings-detail-form" onSubmit={saveDefaults}>
        <Header title={t('worldbook:titles.defaults')} description={t('worldbook:descriptions.defaults')} dirty={defaultsDirty} busy={busy === 'save-defaults'} message={message} />
        <div className="settings-detail-body">
          {localError ? <SettingsApiError error={localError} /> : null}
          <div className="detail-section">
            <div className="detail-section-heading"><h3>{t('worldbook:sections.runtimeDefaults')}</h3></div>
            <BooleanField label={t('worldbook:labels.enableForPromptAgents')} checked={values.worldbook_enabled_for_prompt_agents} onChange={(checked) => setValues({ ...values, worldbook_enabled_for_prompt_agents: checked })} />
            <BooleanField label={t('worldbook:labels.enableForScriptAgents')} checked={values.worldbook_enabled_for_script_agents} onChange={(checked) => setValues({ ...values, worldbook_enabled_for_script_agents: checked })} />
            <BooleanField label={t('worldbook:labels.regexCaseInsensitive')} checked={values.worldbook_regex_case_insensitive} onChange={(checked) => setValues({ ...values, worldbook_regex_case_insensitive: checked })} />
            <div className="settings-detail-grid">
              <NumberField label={t('worldbook:labels.maxEntriesPerCall')} value={values.worldbook_max_entries_per_call} min={1} max={200} onChange={(value) => setValues({ ...values, worldbook_max_entries_per_call: value })} />
              <NumberField label={t('worldbook:labels.maxContextChars')} value={values.worldbook_max_context_chars} min={1000} max={200000} onChange={(value) => setValues({ ...values, worldbook_max_context_chars: value })} />
            </div>
          </div>
        </div>
      </form>
    );
  }

  if (selectedItemId !== 'new' && !selectedWorldbook) {
    return <Empty title={t('worldbook:empty.noWorldbookSelected')} message={t('worldbook:empty.selectWorldbook')} />;
  }

  return (
    <div className="settings-detail-form">
      <Header title={selectedItemId === 'new' ? t('worldbook:titles.newWorldbook') : selectedWorldbook?.name || t('worldbook:titles.worldbook')} description={t('worldbook:descriptions.worldbook')} dirty={false} busy={false} message={message} />
      <DetailTabs
        tabs={[
          { id: 'config', label: t('worldbook:sections.config') },
          { id: 'entries', label: t('worldbook:sections.entries'), enabled: Boolean(selectedWorldbook) },
          { id: 'match', label: t('worldbook:sections.matchTest'), enabled: Boolean(selectedWorldbook) },
        ]}
        activeTab={activeTab}
        onChange={(tab) => setActiveTab(tab as 'config' | 'entries' | 'match')}
      />
      <div className="settings-detail-body">
        {localError ? <SettingsApiError error={localError} /> : null}
        {activeTab === 'config' ? <form className="detail-section" onSubmit={saveWorldbook}>
          <div className="detail-section-heading"><h3>{t('worldbook:sections.config')}</h3></div>
          <TextField label={t('worldbook:labels.name')} value={worldbookValues.name || ''} onChange={(name) => setWorldbookValues({ ...worldbookValues, name })} />
          <TextAreaField label={t('worldbook:labels.description')} value={worldbookValues.description || ''} onChange={(description) => setWorldbookValues({ ...worldbookValues, description })} />
          <BooleanField label={t('worldbook:labels.enabled')} checked={worldbookValues.enabled ?? true} onChange={(enabled) => setWorldbookValues({ ...worldbookValues, enabled })} />
          <div className="settings-button-row">
            <button className="settings-primary-button" type="submit" disabled={busy === 'save-worldbook'}><Save size={14} />{t('common:save')}</button>
            {selectedWorldbook ? <button className="settings-secondary-button danger" type="button" onClick={deleteWorldbook} disabled={Boolean(busy)}><Trash2 size={14} />{t('common:delete')}</button> : null}
          </div>
        </form> : null}
        {selectedWorldbook ? (
          <>
            {activeTab === 'entries' ? <div className="detail-section">
              <div className="detail-section-heading"><h3>{t('worldbook:sections.entries')}</h3></div>
              <div className="settings-button-row"><button className="settings-secondary-button" type="button" onClick={() => setSelectedEntryId('new')}>{t('worldbook:actions.newEntry')}</button></div>
              <div className="settings-list-scroll">
                {entries.map((entry) => (
                  <button
                    key={entry.id}
                    type="button"
                    className={`settings-object-row worldbook-entry-row ${selectedEntryId === entry.id ? 'active' : ''} ${entry.enabled ? '' : 'disabled'} ${dragEntryId === entry.id ? 'dragging' : ''}`}
                    draggable={!busy}
                    onDragStart={(event) => {
                      setDragEntryId(entry.id);
                      event.dataTransfer.effectAllowed = 'move';
                    }}
                    onDragOver={(event) => {
                      if (dragEntryId && dragEntryId !== entry.id) event.preventDefault();
                    }}
                    onDrop={(event) => {
                      event.preventDefault();
                      handleEntryDrop(entry.id);
                    }}
                    onDragEnd={() => setDragEntryId('')}
                    onClick={() => setSelectedEntryId(entry.id)}
                    title={t('worldbook:actions.dragToReorder')}
                  >
                    <GripVertical className="worldbook-drag-handle" size={15} aria-hidden="true" />
                    <div className="settings-object-copy">
                      <strong>{entry.name}</strong>
                      <small>{entry.activation_mode === 'always' ? t('worldbook:labels.alwaysActive') : t('worldbook:labels.keywordTriggered')}</small>
                      {entry.keywords_text ? <small>{keywordPreview(entry.keywords_text)}</small> : null}
                    </div>
                    <span className={`settings-badge ${entry.enabled ? 'success' : 'muted'}`}>{entry.enabled ? t('worldbook:labels.enabled') : t('worldbook:labels.disabled')}</span>
                    <span className="settings-button-row compact" onClick={(event) => event.stopPropagation()}>
                      <button className="settings-secondary-button icon-only" type="button" onClick={() => setSelectedEntryId(entry.id)} title={t('worldbook:actions.editEntry')} aria-label={t('worldbook:actions.editEntry')}><Pencil size={14} /></button>
                    </span>
                  </button>
                ))}
                {!entries.length ? <div className="settings-empty-state compact">{t('worldbook:empty.noEntries')}</div> : null}
              </div>
            </div> : null}
            {(selectedEntryId === 'new' || selectedEntry) ? (
              activeTab === 'entries' ? <form className="detail-section" onSubmit={saveEntry}>
                <div className="detail-section-heading"><h3>{selectedEntryId === 'new' ? t('worldbook:titles.newEntry') : t('worldbook:titles.entry')}</h3></div>
                <TextField label={t('worldbook:labels.name')} value={entryValues.name || ''} onChange={(name) => setEntryValues({ ...entryValues, name })} />
                <SelectField label={t('worldbook:labels.activationMode')} value={entryValues.activation_mode || 'keyword'} onChange={(activation_mode) => setEntryValues({ ...entryValues, activation_mode })} />
                <TextAreaField label={t('worldbook:labels.keywords')} value={entryValues.keywords_text || ''} onChange={(keywords_text) => setEntryValues({ ...entryValues, keywords_text })} />
                <TextAreaField label={t('worldbook:labels.entryContent')} rows={8} value={entryValues.content || ''} onChange={(content) => setEntryValues({ ...entryValues, content })} />
                <BooleanField label={t('worldbook:labels.enabled')} checked={entryValues.enabled ?? true} onChange={(enabled) => setEntryValues({ ...entryValues, enabled })} />
                <div className="settings-button-row">
                  <button className="settings-primary-button" type="submit" disabled={busy === 'save-entry'}><Save size={14} />{t('common:save')}</button>
                  {selectedEntry ? <button className="settings-secondary-button danger" type="button" onClick={deleteEntry} disabled={Boolean(busy)}><Trash2 size={14} />{t('common:delete')}</button> : null}
                </div>
              </form> : null
            ) : null}
            {activeTab === 'match' ? <div className="detail-section">
              <div className="detail-section-heading"><h3>{t('worldbook:sections.matchTest')}</h3></div>
              <TextAreaField label={t('worldbook:labels.matchText')} value={matchText} onChange={setMatchText} />
              <button className="settings-secondary-button" type="button" onClick={runMatchTest} disabled={busy === 'match'}><Play size={14} />{t('worldbook:actions.matchTest')}</button>
              {matchResult ? <MatchResults response={matchResult} /> : null}
            </div> : null}
          </>
        ) : null}
      </div>
    </div>
  );
}

function Header({ title, description, dirty, busy, message }: { title: string; description: string; dirty: boolean; busy: boolean; message: string }) {
  const { t } = useTranslation('common');
  return (
    <header className="settings-detail-header">
      <div className="settings-detail-title"><div className="settings-detail-avatar"><BookOpenText size={18} /></div><div><h2>{title}</h2><p>{description}</p></div></div>
      <div className="settings-detail-actions">
        {message ? <span className="settings-badge success">{message}</span> : null}
        {dirty ? <button className="settings-primary-button" type="submit" disabled={busy}><Save size={14} />{busy ? t('saving') : t('save')}</button> : null}
      </div>
    </header>
  );
}

function BooleanField({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return <label className="config-field settings-config-field boolean-field"><span>{label}</span><ToggleSwitch checked={checked} onChange={onChange} /></label>;
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label className="config-field settings-config-field"><span>{label}</span><input className="settings-form-control" type="text" value={value} onChange={(event) => onChange(event.currentTarget.value)} /></label>;
}

function TextAreaField({ label, value, onChange, rows = 4 }: { label: string; value: string; onChange: (value: string) => void; rows?: number }) {
  return <label className="config-field settings-config-field"><span>{label}</span><textarea className="settings-form-control" rows={rows} value={value} onChange={(event) => onChange(event.currentTarget.value)} /></label>;
}

function NumberField({ label, value, min, max, onChange }: { label: string; value: number; min: number; max: number; onChange: (value: number) => void }) {
  return <label className="config-field settings-config-field"><span>{label}</span><input className="settings-form-control" type="number" min={min} max={max} value={value} onChange={(event) => onChange(Number(event.currentTarget.value))} /></label>;
}

function SelectField({ label, value, onChange }: { label: string; value: 'always' | 'keyword'; onChange: (value: 'always' | 'keyword') => void }) {
  const { t } = useTranslation('worldbook');
  return <label className="config-field settings-config-field"><span>{label}</span><select className="settings-form-control" value={value} onChange={(event) => onChange(event.currentTarget.value as 'always' | 'keyword')}><option value="always">{t('labels.alwaysActive')}</option><option value="keyword">{t('labels.keywordTriggered')}</option></select></label>;
}

function MatchResults({ response }: { response: WorldbookMatchTestResponse }) {
  const { t } = useTranslation('worldbook');
  return (
    <div className="worldbook-match-results">
      <h4>{t('worldbook:labels.matchedEntries')}</h4>
      {response.warnings.length ? <ul className="settings-warning-list">{response.warnings.map((warning, index) => <li key={index}>{warning.message}</li>)}</ul> : null}
      {response.results.length ? response.results.map((result) => (
        <article className="knowledge-result-card" key={result.entry_id}>
          <strong>{result.entry_name}</strong>
          <small>{result.worldbook_name} / {result.activation_mode === 'always' ? t('worldbook:labels.alwaysActive') : t('worldbook:labels.keywordTriggered')}</small>
          {result.matched_keywords.length ? <small>{result.matched_keywords.join(', ')}</small> : null}
          <p>{result.content_preview}</p>
        </article>
      )) : <div className="settings-empty-state compact">{t('worldbook:empty.noMatchedEntries')}</div>}
    </div>
  );
}

function keywordPreview(value: string): string {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean).slice(0, 3).join(', ');
}

function Empty({ title, message }: { title: string; message: string }) {
  return <div className="settings-placeholder"><h2>{title}</h2><p>{message}</p></div>;
}

function worldbookSettingsPatch(values: WorldbookSettings): Partial<WorldbookSettings> {
  const { id, ...patch } = values;
  void id;
  return patch;
}

function worldbookPayload(values: Partial<Worldbook>): WorldbookInput {
  return { name: values.name || '', description: values.description || '', enabled: values.enabled ?? true };
}

function entryPayload(values: Partial<WorldbookEntry>): WorldbookEntryInput {
  return {
    name: values.name || '',
    keywords_text: values.keywords_text || '',
    content: values.content || '',
    activation_mode: values.activation_mode || 'keyword',
    enabled: values.enabled ?? true,
  };
}
