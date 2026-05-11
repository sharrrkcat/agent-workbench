import { BookOpenText, ChevronDown, ChevronRight, GripVertical, Play, RotateCcw, Save, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import type { DragEventHandler, FormEvent, ReactNode } from 'react';
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
  const [entryDrafts, setEntryDrafts] = useState<Record<string, Partial<WorldbookEntry>>>({});
  const [expandedEntryIds, setExpandedEntryIds] = useState<string[]>([]);
  const [matchText, setMatchText] = useState('');
  const [matchResult, setMatchResult] = useState<WorldbookMatchTestResponse | null>(null);
  const [activeTab, setActiveTab] = useState<'config' | 'entries' | 'match'>('config');
  const [dragEntryId, setDragEntryId] = useState('');
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');
  const [localError, setLocalError] = useState<SettingsErrorValue | null>(null);
  const selectedWorldbook = useMemo(() => worldbooks.find((item) => item.id === selectedItemId), [selectedItemId, worldbooks]);
  const defaultsDirty = Boolean(values && settings && JSON.stringify(values) !== JSON.stringify(settings));
  const worldbookDirty = JSON.stringify(worldbookValues) !== JSON.stringify(selectedWorldbook || emptyWorldbook);
  const entryDirty = useMemo(() => {
    return Object.entries(entryDrafts).some(([entryId, draft]) => {
      const source = entryId === 'new' ? emptyEntry : entries.find((entry) => entry.id === entryId);
      return Boolean(source) && JSON.stringify(draft) !== JSON.stringify(source);
    });
  }, [entries, entryDrafts]);

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
      setEntryDrafts({});
      setExpandedEntryIds([]);
      return;
    }
    const nextEntries = await api.listWorldbookEntries(worldbookId);
    setEntries(nextEntries);
    setEntryDrafts(Object.fromEntries(nextEntries.map((entry) => [entry.id, entry])));
    setExpandedEntryIds((current) => current.filter((id) => id === 'new' || nextEntries.some((entry) => entry.id === id)));
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

  async function saveWorldbook(event?: FormEvent) {
    event?.preventDefault();
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

  async function saveEntry(entryId: string, event?: FormEvent) {
    event?.preventDefault();
    if (!selectedWorldbook) return;
    setBusy('save-entry');
    try {
      const draft = entryDrafts[entryId] || (entryId === 'new' ? emptyEntry : entries.find((entry) => entry.id === entryId) || emptyEntry);
      const saved = entryId === 'new'
        ? await api.createWorldbookEntry(selectedWorldbook.id, entryPayload(draft))
        : await api.patchWorldbookEntry(entryId, entryPayload(draft));
      setMessage(t('worldbook:results.entrySaved'));
      await loadEntries(selectedWorldbook.id);
      setExpandedEntryIds((current) => uniqueIds(current.filter((id) => id !== 'new').concat(saved.id)));
    } catch (error) {
      setLocalError(toSettingsError(error, t('worldbook:errors.saveEntryFailed')));
    } finally {
      setBusy('');
    }
  }

  async function deleteEntry(entryId: string) {
    if (!selectedWorldbook || entryId === 'new') {
      resetEntry(entryId);
      return;
    }
    setBusy('delete-entry');
    try {
      await api.deleteWorldbookEntry(entryId);
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

  function newEntry() {
    setEntryDrafts((current) => ({ ...current, new: { ...emptyEntry } }));
    setExpandedEntryIds((current) => uniqueIds(['new', ...current]));
  }

  function toggleEntry(entryId: string) {
    setExpandedEntryIds((current) => current.includes(entryId) ? current.filter((id) => id !== entryId) : [...current, entryId]);
  }

  function updateEntryDraft(entryId: string, patch: Partial<WorldbookEntry>) {
    setEntryDrafts((current) => {
      const source = current[entryId] || (entryId === 'new' ? emptyEntry : entries.find((entry) => entry.id === entryId) || emptyEntry);
      return { ...current, [entryId]: { ...source, ...patch } };
    });
  }

  function resetEntry(entryId: string) {
    if (entryId === 'new') {
      setEntryDrafts((current) => {
        const { new: _newEntry, ...rest } = current;
        void _newEntry;
        return rest;
      });
      setExpandedEntryIds((current) => current.filter((id) => id !== 'new'));
      return;
    }
    const source = entries.find((entry) => entry.id === entryId);
    if (!source) return;
    setEntryDrafts((current) => ({ ...current, [entryId]: source }));
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

  const worldbookHeaderActions = category === 'worldbooks' ? (
    <>
      {message ? <span className="settings-badge success">{message}</span> : null}
      {worldbookDirty ? (
        <button className="settings-primary-button" type="button" onClick={() => void saveWorldbook()} disabled={busy === 'save-worldbook'}>
          <Save size={14} />
          {busy === 'save-worldbook' ? t('common:saving') : t('common:save')}
        </button>
      ) : null}
      {selectedWorldbook ? (
        <button className="settings-secondary-button danger" type="button" onClick={deleteWorldbook} disabled={Boolean(busy)}>
          <Trash2 size={14} />
          {t('common:delete')}
        </button>
      ) : null}
      <ToggleSwitch checked={worldbookValues.enabled ?? true} onChange={(enabled) => setWorldbookValues({ ...worldbookValues, enabled })} disabled={Boolean(busy)} />
    </>
  ) : undefined;

  return (
    <div className="settings-detail-form">
      <Header
        title={selectedItemId === 'new' ? t('worldbook:titles.newWorldbook') : selectedWorldbook?.name || t('worldbook:titles.worldbook')}
        description={t('worldbook:descriptions.worldbook')}
        dirty={false}
        busy={false}
        message=""
        actions={worldbookHeaderActions}
      />
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
        </form> : null}
        {selectedWorldbook ? (
          <>
            {activeTab === 'entries' ? <div className="detail-section">
              <div className="detail-section-heading"><h3>{t('worldbook:sections.entries')}</h3></div>
              <div className="settings-button-row"><button className="settings-secondary-button" type="button" onClick={newEntry}>{t('worldbook:actions.newEntry')}</button></div>
              <div className="worldbook-entry-card-list">
                {expandedEntryIds.includes('new') ? (
                  <EntryCard
                    entryId="new"
                    draft={entryDrafts.new || emptyEntry}
                    expanded
                    dirty={JSON.stringify(entryDrafts.new || emptyEntry) !== JSON.stringify(emptyEntry)}
                    busy={busy}
                    draggable={false}
                    onToggle={() => toggleEntry('new')}
                    onUpdate={(patch) => updateEntryDraft('new', patch)}
                    onSave={(event) => void saveEntry('new', event)}
                    onReset={() => resetEntry('new')}
                    onDelete={() => resetEntry('new')}
                  />
                ) : null}
                {entries.map((entry) => {
                  const draft = entryDrafts[entry.id] || entry;
                  const expanded = expandedEntryIds.includes(entry.id);
                  return (
                    <EntryCard
                      key={entry.id}
                      entryId={entry.id}
                      entry={entry}
                      draft={draft}
                      expanded={expanded}
                      dirty={JSON.stringify(draft) !== JSON.stringify(entry)}
                      busy={busy}
                      draggable={!busy}
                      dragging={dragEntryId === entry.id}
                      onToggle={() => toggleEntry(entry.id)}
                      onUpdate={(patch) => updateEntryDraft(entry.id, patch)}
                      onSave={(event) => void saveEntry(entry.id, event)}
                      onReset={() => resetEntry(entry.id)}
                      onDelete={() => void deleteEntry(entry.id)}
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
                    />
                  );
                })}
                {!entries.length && !expandedEntryIds.includes('new') ? <div className="settings-empty-state compact">{t('worldbook:empty.noEntries')}</div> : null}
              </div>
            </div> : null}
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

function EntryCard({
  entryId,
  entry,
  draft,
  expanded,
  dirty,
  busy,
  draggable,
  dragging = false,
  onToggle,
  onUpdate,
  onSave,
  onReset,
  onDelete,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
}: {
  entryId: string;
  entry?: WorldbookEntry;
  draft: Partial<WorldbookEntry>;
  expanded: boolean;
  dirty: boolean;
  busy: string;
  draggable: boolean;
  dragging?: boolean;
  onToggle: () => void;
  onUpdate: (patch: Partial<WorldbookEntry>) => void;
  onSave: (event: FormEvent) => void;
  onReset: () => void;
  onDelete: () => void;
  onDragStart?: DragEventHandler<HTMLButtonElement>;
  onDragOver?: DragEventHandler<HTMLElement>;
  onDrop?: DragEventHandler<HTMLElement>;
  onDragEnd?: DragEventHandler<HTMLButtonElement>;
}) {
  const { t } = useTranslation(['worldbook', 'common']);
  const title = draft.name || (entryId === 'new' ? t('worldbook:titles.newEntry') : t('worldbook:titles.entry'));
  const activationModeLabel = draft.activation_mode === 'always' ? t('worldbook:labels.alwaysActive') : t('worldbook:labels.keywordTriggered');

  return (
    <article
      className={`worldbook-entry-card ${expanded ? 'expanded' : ''} ${draft.enabled ?? true ? '' : 'disabled'} ${dragging ? 'dragging' : ''}`}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <header className="worldbook-entry-card-header" onClick={onToggle}>
        <button
          className="worldbook-drag-button"
          type="button"
          draggable={draggable}
          disabled={!draggable}
          onDragStart={onDragStart}
          onDragEnd={onDragEnd}
          onClick={(event) => event.stopPropagation()}
          title={t('worldbook:actions.dragToReorder')}
          aria-label={t('worldbook:actions.dragToReorder')}
        >
          <GripVertical size={15} aria-hidden="true" />
        </button>
        <button
          className="settings-secondary-button icon-only"
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onToggle();
          }}
          title={expanded ? t('worldbook:actions.collapseEntry') : t('worldbook:actions.expandEntry')}
          aria-label={expanded ? t('worldbook:actions.collapseEntry') : t('worldbook:actions.expandEntry')}
        >
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        <ToggleSwitch
          checked={draft.enabled ?? true}
          onChange={(enabled) => onUpdate({ enabled })}
          showLabel={false}
          size="small"
          disabled={Boolean(busy)}
        />
        <div className="worldbook-entry-card-title">
          <strong>{title}</strong>
        </div>
        <div className="worldbook-entry-card-actions">
          {dirty ? <span className="settings-badge warning">{t('worldbook:labels.unsavedChanges')}</span> : null}
          <span className="settings-badge muted worldbook-entry-mode-chip">{activationModeLabel}</span>
          <button
            className="settings-secondary-button danger icon-only"
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onDelete();
            }}
            disabled={Boolean(busy)}
            title={t('common:delete')}
            aria-label={t('common:delete')}
          >
            <Trash2 size={14} />
          </button>
        </div>
      </header>
      {expanded ? (
        <form className="worldbook-entry-card-body" onSubmit={onSave}>
          <div className="worldbook-entry-form-row">
            <TextField label={t('worldbook:labels.name')} value={draft.name || ''} onChange={(name) => onUpdate({ name })} />
            <SelectField label={t('worldbook:labels.activationMode')} value={draft.activation_mode || 'keyword'} onChange={(activation_mode) => onUpdate({ activation_mode })} />
          </div>
          <TextField label={t('worldbook:labels.keywords')} value={draft.keywords_text || ''} onChange={(keywords_text) => onUpdate({ keywords_text })} />
          <TextAreaField label={t('worldbook:labels.entryContent')} rows={8} value={draft.content || ''} onChange={(content) => onUpdate({ content })} />
          <div className="settings-button-row">
            <button className="settings-primary-button" type="submit" disabled={busy === 'save-entry'}>
              <Save size={14} />
              {busy === 'save-entry' ? t('common:saving') : t('common:save')}
            </button>
            <button className="settings-secondary-button" type="button" onClick={onReset} disabled={!dirty || Boolean(busy)}>
              <RotateCcw size={14} />
              {t('worldbook:actions.resetEntry')}
            </button>
            <button className="settings-secondary-button danger" type="button" onClick={onDelete} disabled={Boolean(busy)}>
              <Trash2 size={14} />
              {t('common:delete')}
            </button>
          </div>
        </form>
      ) : null}
    </article>
  );
}

function Header({ title, description, dirty, busy, message, actions }: { title: string; description: string; dirty: boolean; busy: boolean; message: string; actions?: ReactNode }) {
  const { t } = useTranslation('common');
  return (
    <header className="settings-detail-header">
      <div className="settings-detail-title"><div className="settings-detail-avatar"><BookOpenText size={18} /></div><div><h2>{title}</h2><p>{description}</p></div></div>
      <div className="settings-detail-actions">
        {actions || (
          <>
            {message ? <span className="settings-badge success">{message}</span> : null}
            {dirty ? <button className="settings-primary-button" type="submit" disabled={busy}><Save size={14} />{busy ? t('saving') : t('save')}</button> : null}
          </>
        )}
      </div>
    </header>
  );
}

function BooleanField({ label, checked, onChange, compact = false }: { label: string; checked: boolean; onChange: (checked: boolean) => void; compact?: boolean }) {
  return <label className={`config-field settings-config-field boolean-field ${compact ? 'compact' : ''}`}><span>{label}</span><ToggleSwitch checked={checked} onChange={onChange} /></label>;
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

function uniqueIds(values: string[]): string[] {
  return Array.from(new Set(values));
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
