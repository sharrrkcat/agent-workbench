import { ResourceEmpty } from './resources/ResourceUI';
import { SettingsView } from './SettingsView';
import type { ResourceView } from './navigation';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Database, ChevronRight, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { knowledgeApi } from '../../api/knowledge';
import type { KnowledgeBase } from '../../types/knowledge';
import { useModelsStore } from '../../store/useModelsStore';
import { KnowledgeDetail } from './knowledge/KnowledgeDetail';
import { KnowledgeDefaults } from './knowledge/KnowledgeDefaults';
import {
  errorText,
  Feedback,
  ResourceLoading,
  useResourceGuard,
  useResourceTask,
  revealInvalidField,
} from './resources/ResourceUI';

export function KnowledgePanel({ view }: { view: ResourceView }) {
  const { confirm, confirmation } = useConfirmDialog();
  const { t } = useTranslation('knowledge');
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [selected, setSelected] = useState('');
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    panel.current?.closest('.settings-scroll')?.scrollTo(0, 0);
  }, [selected]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [detailState, setDetailState] = useState({ dirty: false, busy: false });
  const [settingsState, setSettingsState] = useState({ dirty: false, busy: false });
  const modelsError = useModelsStore((state) => state.error);
  const reloadModels = useModelsStore((state) => state.reload);
  const task = useResourceTask();
  const leaveDetail = useCallback(() => {
    setSelected('');
    setDetailState({ dirty: false, busy: false });
  }, []);
  useResourceGuard(
    {
      section: 'knowledge',
      detail: detailState,
      settings: settingsState,
      busy: !!task.busy,
      onLeaveDetail: leaveDetail,
    },
    confirm,
  );
  useEffect(() => {
    void reloadModels().catch(() => undefined);
  }, [reloadModels]);
  useEffect(() => {
    let live = true;
    void knowledgeApi
      .listKnowledgeBases()
      .then((values) => {
        if (live) {
          setBases(values);
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
  const saved = useCallback((base: KnowledgeBase, created: boolean) => {
    setBases((current) =>
      current.some((item) => item.id === base.id)
        ? current.map((item) => (item.id === base.id ? base : item))
        : [...current, base],
    );
    if (created) {
      setSelected(base.id);
      setDetailState({ dirty: false, busy: false });
    }
  }, []);
  async function refresh() {
    setBases(await knowledgeApi.listKnowledgeBases());
    setLoadError('');
  }
  return (
    <section ref={panel} className="settings-panel resource-panel" onInvalidCapture={revealInvalidField}>
      {modelsError ? (
        <ResourceLoading error={modelsError} retry={() => void reloadModels().catch(() => undefined)} />
      ) : null}
      <SettingsView active={view === 'list'}>
        {selected ? (
          <KnowledgeDetail
            key={selected}
            id={selected}
            onBack={back}
            onState={setDetailState}
            onSaved={saved}
            onDeleted={() => {
              setBases((current) => current.filter((item) => item.id !== selected));
              setSelected('');
              setDetailState({ dirty: false, busy: false });
            }}
          />
        ) : (
          <>
            <div className="resource-heading">
              <Database data-icon="inline-start" />
              <h2>{t('title')}</h2>
            </div>

            <div className="resource-toolbar">
              <span>{t('baseCount', { count: bases.length })}</span>
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
                        onClick={() => void task.run('load', refresh)}
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
                  {t('addBase')}
                </Button>
              </div>
            </div>
            <Feedback {...task} />
            {loading || loadError ? (
              <ResourceLoading error={loadError} retry={() => void task.run('load', refresh)} />
            ) : bases.length ? (
              <div className="resource-list">
                {bases.map((base) => (
                  <div className="resource-row" key={base.id}>
                    <div className="resource-identity">
                      <strong>{base.name}</strong>
                      <small>
                        {t(base.enabled ? 'enabled' : 'disabled')} · {t('statuses.' + base.index_status)}
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
                              aria-label={t('settings:resources.manageNamed', { name: base.name })}
                              disabled={!!task.busy}
                              onClick={() => setSelected(base.id)}
                            />
                          }
                        >
                          <ChevronRight data-icon="inline-start" />
                        </TooltipTrigger>
                        <TooltipContent>
                          {t('settings:resources.manageNamed', { name: base.name })}
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
                                  await confirm(t('deleteBaseConfirm', { name: base.name }), {
                                    destructive: true,
                                  })
                                )
                                  void task.run('delete', async () => {
                                    await knowledgeApi.deleteKnowledgeBase(base.id);
                                    setBases((current) => current.filter((item) => item.id !== base.id));
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
              <ResourceEmpty>{t('noBases')}</ResourceEmpty>
            )}
          </>
        )}
      </SettingsView>
      <SettingsView active={view === 'settings'}>
        <KnowledgeDefaults onState={setSettingsState} />
      </SettingsView>
      {confirmation}
    </section>
  );
}
