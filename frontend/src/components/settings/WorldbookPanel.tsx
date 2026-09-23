import { ResourceEmpty } from './resources/ResourceUI';
import { SettingsView } from './SettingsView';
import type { ResourceView } from './navigation';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { useCallback, useEffect, useRef, useState } from 'react';
import { BookOpenText, ChevronRight, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { worldbookApi } from '../../api/worldbook';
import type { Worldbook } from '../../types/worldbook';
import { WorldbookDetail } from './worldbook/WorldbookDetail';
import { WorldbookDefaults } from './worldbook/WorldbookDefaults';
import {
  errorText,
  Feedback,
  ResourceLoading,
  useResourceGuard,
  useResourceTask,
  revealInvalidField,
} from './resources/ResourceUI';

export function WorldbookPanel({ view }: { view: ResourceView }) {
  const { confirm, confirmation } = useConfirmDialog();
  const { t } = useTranslation('worldbook');
  const [books, setBooks] = useState<Worldbook[]>([]);
  const [selected, setSelected] = useState('');
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    panel.current?.closest('.settings-scroll')?.scrollTo(0, 0);
  }, [selected]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [detailState, setDetailState] = useState({ dirty: false, busy: false });
  const [settingsState, setSettingsState] = useState({ dirty: false, busy: false });
  const task = useResourceTask();
  const leaveDetail = useCallback(() => {
    setSelected('');
    setDetailState({ dirty: false, busy: false });
  }, []);
  useResourceGuard(
    {
      section: 'worldbook',
      detail: detailState,
      settings: settingsState,
      busy: !!task.busy,
      onLeaveDetail: leaveDetail,
    },
    confirm,
  );
  async function reload() {
    setBooks(await worldbookApi.listWorldbooks());
  }
  useEffect(() => {
    let live = true;
    void worldbookApi
      .listWorldbooks()
      .then((values) => {
        if (live) {
          setBooks(values);
          setLoading(false);
        }
      })
      .catch((reason) => {
        if (live) {
          setLoadError(errorText(reason));
          setLoading(false);
        }
      });
    return () => {
      live = false;
    };
  }, []);
  async function back() {
    if (
      !detailState.busy &&
      (!detailState.dirty || (await confirm(t('settings:resources.discardConfirm'))))
    ) {
      setSelected('');
      setDetailState({ dirty: false, busy: false });
    }
  }
  return (
    <section ref={panel} className="settings-panel resource-panel" onInvalidCapture={revealInvalidField}>
      <SettingsView active={view === 'list'}>
        {selected ? (
          <WorldbookDetail
            key={selected}
            id={selected}
            onBack={back}
            onState={setDetailState}
            onSaved={(book, created) => {
              setBooks((current) =>
                current.some((item) => item.id === book.id)
                  ? current.map((item) => (item.id === book.id ? book : item))
                  : [...current, book],
              );
              if (created) {
                setDetailState({ dirty: false, busy: false });
                setSelected(book.id);
              }
            }}
            onDeleted={() => {
              setBooks((current) => current.filter((item) => item.id !== selected));
              setSelected('');
              setDetailState({ dirty: false, busy: false });
            }}
          />
        ) : (
          <>
            <div className="resource-heading">
              <BookOpenText data-icon="inline-start" />
              <h2>{t('title')}</h2>
            </div>

            <div className="resource-toolbar">
              <span>{t('bookCount', { count: books.length })}</span>
              <div className="resource-actions">
                <Tooltip>
                  <TooltipTrigger
                    render={
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={t('settings:resources.refresh')}
                        disabled={!!task.busy}
                        onClick={() =>
                          void task.run('load', async () => {
                            await reload();
                            setLoadError('');
                          })
                        }
                      />
                    }
                  >
                    <RefreshCw data-icon="inline-start" />
                  </TooltipTrigger>
                  <TooltipContent>{t('settings:resources.refresh')}</TooltipContent>
                </Tooltip>
                <Button
                  type="button"
                  disabled={!!task.busy}
                  onClick={() => setSelected('new')}
                  variant="outline"
                >
                  <Plus data-icon="inline-start" />
                  {t('addWorldbook')}
                </Button>
              </div>
            </div>
            <Feedback {...task} />
            {loading || loadError ? (
              <ResourceLoading
                error={loadError}
                retry={() =>
                  void task.run('load', async () => {
                    await reload();
                    setLoadError('');
                  })
                }
              />
            ) : books.length ? (
              <div className="resource-list">
                {books.map((book) => (
                  <div className="resource-row" key={book.id}>
                    <div className="resource-identity">
                      <strong>{book.name}</strong>
                      <small>
                        {t('entryCount', { count: book.entry_count || 0 })} ·{' '}
                        {t(book.enabled ? 'bookEnabled' : 'bookDisabled')}
                      </small>
                    </div>
                    <div className="resource-actions">
                      <Tooltip>
                        <TooltipTrigger
                          render={
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              aria-label={t('settings:resources.manageNamed', { name: book.name })}
                              disabled={!!task.busy}
                              onClick={() => setSelected(book.id)}
                            />
                          }
                        >
                          <ChevronRight data-icon="inline-start" />
                        </TooltipTrigger>
                        <TooltipContent>
                          {t('settings:resources.manageNamed', { name: book.name })}
                        </TooltipContent>
                      </Tooltip>
                      <Tooltip>
                        <TooltipTrigger
                          render={
                            <Button
                              type="button"
                              variant="destructive"
                              size="icon"
                              aria-label={t('common:delete')}
                              disabled={!!task.busy}
                              onClick={async () => {
                                if (
                                  await confirm(t('deleteBookConfirm', { name: book.name }), {
                                    destructive: true,
                                  })
                                )
                                  void task.run('delete', async () => {
                                    await worldbookApi.deleteWorldbook(book.id);
                                    setBooks((current) => current.filter((item) => item.id !== book.id));
                                  });
                              }}
                            />
                          }
                        >
                          <Trash2 data-icon="inline-start" />
                        </TooltipTrigger>
                        <TooltipContent>{t('common:delete')}</TooltipContent>
                      </Tooltip>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <ResourceEmpty>{t('noWorldbooks')}</ResourceEmpty>
            )}
          </>
        )}
      </SettingsView>
      <SettingsView active={view === 'settings'}>
        <WorldbookDefaults onState={setSettingsState} />
      </SettingsView>
      {confirmation}
    </section>
  );
}
