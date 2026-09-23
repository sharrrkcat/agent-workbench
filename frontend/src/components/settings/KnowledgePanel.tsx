import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { useCallback, useEffect, useState } from 'react';
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

export function KnowledgePanel() {
  const { confirm, confirmation } = useConfirmDialog();
  const { t } = useTranslation('knowledge');
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [selected, setSelected] = useState('');
  const [tab, setTab] = useState<'list' | 'settings'>('list');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [detailState, setDetailState] = useState({ dirty: false, busy: false });
  const [settingsState, setSettingsState] = useState({ dirty: false, busy: false });
  const modelsError = useModelsStore((state) => state.error);
  const reloadModels = useModelsStore((state) => state.reload);
  const task = useResourceTask();
  useResourceGuard(
    detailState.dirty || settingsState.dirty,
    detailState.busy || settingsState.busy || !!task.busy,
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
    <Tabs
      value={tab}
      onValueChange={setTab}
      render={<section className="settings-panel resource-panel" onInvalidCapture={revealInvalidField} />}
    >
      {modelsError ? (
        <ResourceLoading error={modelsError} retry={() => void reloadModels().catch(() => undefined)} />
      ) : null}
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
            <Database size={22} />
            <h2>{t('title')}</h2>
          </div>
          <TabsList aria-label={t('settings:resources.sections')}>
            {[
              { id: 'list', label: t('settings:resources.list') },
              { id: 'settings', label: t('settings:resources.settings') },
            ].map((item) => (
              <TabsTrigger key={item.id} value={item.id} disabled={'disabled' in item && !!item.disabled}>
                {item.label}
              </TabsTrigger>
            ))}
          </TabsList>
          <TabsContent value="list" keepMounted hidden={tab !== 'list'}>
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
                    <RefreshCw size={16} />
                  </TooltipTrigger>
                  <TooltipContent>{t('settings:resources.refresh')}</TooltipContent>
                </Tooltip>
                <Button
                  type="button"
                  disabled={!!task.busy}
                  onClick={() => setSelected('new')}
                  variant="outline"
                >
                  <Plus size={16} />
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
                          <ChevronRight size={18} />
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
                          <Trash2 size={16} />
                        </TooltipTrigger>
                        <TooltipContent>{t('common:delete')}</TooltipContent>
                      </Tooltip>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="resource-empty">{t('noBases')}</p>
            )}
          </TabsContent>
        </>
      )}
      <TabsContent value="settings" keepMounted hidden={!!selected || tab !== 'settings'}>
        <KnowledgeDefaults onState={setSettingsState} />
      </TabsContent>
      {confirmation}
    </Tabs>
  );
}
