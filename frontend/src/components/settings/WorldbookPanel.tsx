import { useEffect, useState } from 'react';
import { BookOpenText, ChevronRight, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { worldbookApi } from '../../api/worldbook';
import type { Worldbook } from '../../types/worldbook';
import { WorldbookDetail } from './worldbook/WorldbookDetail';
import { WorldbookDefaults } from './worldbook/WorldbookDefaults';
import { errorText, Feedback, ResourceIcon, ResourceLoading, ResourceTabs, useResourceGuard, useResourceTask, revealInvalidField } from './resources/ResourceUI';

export function WorldbookPanel() {
  const { t } = useTranslation('worldbook');
  const [books, setBooks] = useState<Worldbook[]>([]);
  const [selected, setSelected] = useState('');
  const [tab, setTab] = useState<'list' | 'settings'>('list');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [detailState, setDetailState] = useState({ dirty: false, busy: false });
  const [settingsState, setSettingsState] = useState({ dirty: false, busy: false });
  const task = useResourceTask();
  useResourceGuard(detailState.dirty || settingsState.dirty, detailState.busy || settingsState.busy || !!task.busy);
  async function reload() { setBooks(await worldbookApi.listWorldbooks()); }
  useEffect(() => {
    let live = true;
    void worldbookApi.listWorldbooks().then((values) => { if (live) { setBooks(values); setLoading(false); } })
      .catch((reason) => { if (live) { setLoadError(errorText(reason)); setLoading(false); } });
    return () => { live = false; };
  }, []);
  function back() { if (!detailState.busy && (!detailState.dirty || window.confirm(t('settings:resources.discardConfirm')))) { setSelected(''); setDetailState({ dirty: false, busy: false }); } }
  return <section className="settings-panel resource-panel" onInvalidCapture={revealInvalidField}>
    {selected ? <WorldbookDetail key={selected} id={selected} onBack={back} onState={setDetailState}
      onSaved={(book, created) => { setBooks((current) => current.some((item) => item.id === book.id) ? current.map((item) => item.id === book.id ? book : item) : [...current, book]); if (created) { setDetailState({ dirty: false, busy: false }); setSelected(book.id); } }}
      onDeleted={() => { setBooks((current) => current.filter((item) => item.id !== selected)); setSelected(''); setDetailState({ dirty: false, busy: false }); }} /> : <>
      <div className="resource-heading"><BookOpenText size={22} /><h2>{t('title')}</h2></div>
      <ResourceTabs value={tab} onChange={setTab} tabs={[{ id: 'list', label: t('settings:resources.list') }, { id: 'settings', label: t('settings:resources.settings') }]} />
      <div hidden={tab !== 'list'}>
        <div className="resource-toolbar"><span>{t('bookCount', { count: books.length })}</span><div className="resource-actions">
          <ResourceIcon label={t('settings:resources.refresh')} disabled={!!task.busy} onClick={() => void task.run('load', async () => { await reload(); setLoadError(''); })}><RefreshCw size={16} /></ResourceIcon>
          <button type="button" className="secondary-button" disabled={!!task.busy} onClick={() => setSelected('new')}><Plus size={16} />{t('addWorldbook')}</button>
        </div></div>
        <Feedback {...task} />
        {loading || loadError ? <ResourceLoading error={loadError} retry={() => void task.run('load', async () => { await reload(); setLoadError(''); })} /> : books.length ? <div className="resource-list">{books.map((book) => <div className="resource-row" key={book.id}>
          <div className="resource-identity"><strong>{book.name}</strong><small>{t('entryCount', { count: book.entry_count || 0 })} · {t(book.enabled ? 'bookEnabled' : 'bookDisabled')}</small></div>
          <div className="resource-actions"><ResourceIcon label={t('settings:resources.manageNamed', { name: book.name })} disabled={!!task.busy} onClick={() => setSelected(book.id)}><ChevronRight size={18} /></ResourceIcon>
            <ResourceIcon label={t('common:delete')} danger disabled={!!task.busy} onClick={() => { if (window.confirm(t('deleteBookConfirm', { name: book.name }))) void task.run('delete', async () => { await worldbookApi.deleteWorldbook(book.id); setBooks((current) => current.filter((item) => item.id !== book.id)); }); }}><Trash2 size={16} /></ResourceIcon></div>
        </div>)}</div> : <p className="resource-empty">{t('noWorldbooks')}</p>}
      </div>
    </>}
    <div hidden={!!selected || tab !== 'settings'}><WorldbookDefaults onState={setSettingsState} /></div>
  </section>;
}
