import { Badge } from '@/components/ui/badge';
import { ResourceEmpty } from '../resources/ResourceUI';
import { useSettingsView } from '../SettingsView';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectGroup,
  SelectItem,
} from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Activity, Copy, FileText, Pencil, Play, Plus, RefreshCw, Square, Trash2 } from 'lucide-react';
import { useState } from 'react';

import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import { useModelsStore } from '../../../store/useModelsStore';
import type { ModelKind, ModelInventoryItem, SiglipTower } from '../../../types/models';

import type { ModelFeedbackProps } from './types';
import { kinds, localSource, newModel } from './profileDefaults';
import { ProfileEditor, type ProfileDraft } from './ProfileEditor';
import { SiglipStatus, TowerActionMenu } from './SiglipControls';

export function ProfilesTab({
  run,
  busy,
  feedback,
  setError,
  onOpenLocalRuntime,
}: ModelFeedbackProps & { onOpenLocalRuntime: () => void }) {
  const { t } = useTranslation('llm');
  const activeView = useSettingsView();
  const { profiles, statuses, setStatus, loading } = useModelsStore();
  const [kind, setKind] = useState<ModelKind>('llm');
  const [model, setModel] = useState<ProfileDraft | null>(null);
  const [inventory, setInventory] = useState<ModelInventoryItem[]>([]);
  const [processLog, setProcessLog] = useState<{ title: string; text: string } | null>(null);
  const openLog = (id: string, tower?: SiglipTower) => run(async () => {
    const { text } = await modelsApi.getModelLog(id, tower);
    setProcessLog({ title: tower ? t('siglip.log.' + tower) : t('processLog'), text });
  }, false);
  const statusAction = (id: string, action: 'load' | 'unload' | 'health', tower?: SiglipTower) =>
    run(async () => {
      try {
        setStatus(id, await modelsApi.modelAction(id, action, tower));
      } finally {
        setStatus(id, await modelsApi.getModelStatus(id));
      }
    }, false);
  return (
    <>
      <>
        <div className="model-toolbar">
          <Select
            key={String(activeView)}
            value={kind}
            onValueChange={(selected) => setKind((selected ?? '') as ModelKind)}
            items={kinds.map((k) => ({ value: k, label: t('kinds.' + k) }))}
          >
            <SelectTrigger className="w-full sm:w-56" aria-label={t('kind')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {kinds.map((k) => (
                  <SelectItem key={k} value={k}>
                    {t('kinds.' + k)}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <div className="model-actions">
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label={t('inventory')}
                    disabled={busy}
                    onClick={() =>
                      void run(async () => setInventory(await modelsApi.listModelInventory(kind)), false)
                    }
                  />
                }
              >
                <RefreshCw data-icon="inline-start" />
              </TooltipTrigger>
              <TooltipContent>{t('inventory')}</TooltipContent>
            </Tooltip>
            <Button
              disabled={busy}
              onClick={() => {
                setError('');
                setModel({ value: newModel(kind) });
              }}
              type="button"
              variant="outline"
            >
              <Plus data-icon="inline-start" />
              {t('addModel')}
            </Button>
          </div>
        </div>
        <div className="model-list">
          {profiles
            .filter((p) => p.kind === kind)
            .map((p) => {
              const status = statuses[p.id];
              return (
                <div className="model-row" key={p.id}>
                  <div className="model-identity">
                    <strong>{p.name}</strong>
                    <code>{p.alias}</code>
                    <small>{p.model_ref}</small>
                    {p.source?.type === 'provider' ? <small>{t('recentRequestState')}</small> : null}
                  </div>
                  <div className="model-state">
                    <Badge variant="secondary">
                      {p.enabled ? t('states.' + (status?.state || 'unknown')) : t('disabled')}
                    </Badge>
                    {p.source?.type === 'local' ? (
                      <small>
                        {t('residency')}: {t('residencies.' + (status?.residency || 'unknown'))}
                      </small>
                    ) : null}
                    <small>
                      {t('active')}: {status?.active || 0} / {t('queued')}: {status?.queued || 0}
                    </small>
                  </div>
                  <div className="model-actions">
                    {p.source?.type === 'local' ? (
                      <>
                        <Tooltip>
                          <TooltipTrigger
                            render={
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                aria-label={t('health')}
                                disabled={busy || !p.enabled || !p.source}
                                onClick={() => void statusAction(p.id, 'health')}
                              />
                            }
                          >
                            <Activity data-icon="inline-start" />
                          </TooltipTrigger>
                          <TooltipContent>{t('health')}</TooltipContent>
                        </Tooltip>
                        {p.kind === 'image_embedding' ? (
                          <TowerActionMenu action="load" disabled={busy || !p.enabled}
                            onSelect={(tower) => void statusAction(p.id, 'load', tower)} />
                        ) : <Tooltip>
                          <TooltipTrigger
                            render={
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                aria-label={t('load')}
                                disabled={busy || !p.enabled || !p.source}
                                onClick={() => void statusAction(p.id, 'load')}
                              />
                            }
                          >
                            <Play data-icon="inline-start" />
                          </TooltipTrigger>
                          <TooltipContent>{t('load')}</TooltipContent>
                        </Tooltip>}
                        <Tooltip>
                          <TooltipTrigger
                            render={
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                aria-label={status?.unload_supported ? t('unload') : t('unloadUnsupported')}
                                disabled={
                                  busy ||
                                  !status?.unload_supported ||
                                  !!status.active ||
                                  !!status.queued ||
                                  (!!status.runtime && status.runtime.install_state !== 'installed')
                                }
                                onClick={() => void statusAction(p.id, 'unload')}
                              />
                            }
                          >
                            <Square data-icon="inline-start" />
                          </TooltipTrigger>
                          <TooltipContent>
                            {status?.unload_supported ? t('unload') : t('unloadUnsupported')}
                          </TooltipContent>
                        </Tooltip>
                        {p.kind === 'image_embedding' ? (
                          <TowerActionMenu action="log" disabled={busy}
                            onSelect={(tower) => void openLog(p.id, tower)} />
                        ) : <Tooltip>
                          <TooltipTrigger
                            render={
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                aria-label={t('processLog')}
                                disabled={busy}
                                onClick={() => void openLog(p.id)}
                              />
                            }
                          >
                            <FileText data-icon="inline-start" />
                          </TooltipTrigger>
                          <TooltipContent>{t('processLog')}</TooltipContent>
                        </Tooltip>}
                      </>
                    ) : null}
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            aria-label={t('edit')}
                            disabled={busy}
                            onClick={() => {
                              const { id, created_at: _c, updated_at: _u, ...value } = p;
                              setError('');
                              setModel({ id, value });
                            }}
                          />
                        }
                      >
                        <Pencil data-icon="inline-start" />
                      </TooltipTrigger>
                      <TooltipContent>{t('edit')}</TooltipContent>
                    </Tooltip>
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            aria-label={t('duplicate')}
                            disabled={busy}
                            onClick={() => {
                              const { id: _id, created_at: _c, updated_at: _u, ...value } = p;
                              setError('');
                              setModel({
                                value: { ...value, alias: p.alias + '-copy', name: p.name + ' ' + t('copy') },
                              });
                            }}
                          />
                        }
                      >
                        <Copy data-icon="inline-start" />
                      </TooltipTrigger>
                      <TooltipContent>{t('duplicate')}</TooltipContent>
                    </Tooltip>
                    <Tooltip>
                      <TooltipTrigger
                        render={
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            aria-label={t('delete')}
                            disabled={busy}
                            onClick={() => void run(() => modelsApi.deleteModelProfile(p.id))}
                          />
                        }
                      >
                        <Trash2 data-icon="inline-start" />
                      </TooltipTrigger>
                      <TooltipContent>{t('delete')}</TooltipContent>
                    </Tooltip>
                  </div>
                  {status?.error_code && !status.runtime ? (
                    <code className="error-text">{status.error_code}</code>
                  ) : null}
                  {status?.runtime ? (
                    <div className="model-runtime-state">
                      <span>
                        {t('engines.' + status.runtime.engine)} / {status.runtime.version}:{' '}
                        {t('runtimeStates.' + status.runtime.install_state)}
                      </span>
                      {status.runtime.device_name ? <span>{status.runtime.device_name}</span> : null}
                      {status.runtime.gpu_layers_loaded != null ? (
                        <span>
                          {t('gpuOffloaded', {
                            loaded: status.runtime.gpu_layers_loaded,
                            total: status.runtime.gpu_layers_total,
                          })}
                        </span>
                      ) : null}
                      {status.error_code ? <code className="error-text">{status.error_code}</code> : null}
                      {status.runtime.install_state !== 'installed' ? (
                        <Button
                          type="button"
                          onClick={() => onOpenLocalRuntime()}
                          variant="ghost"
                          className="text-button"
                        >
                          {t('manageLocalRuntime')}
                        </Button>
                      ) : null}
                    </div>
                  ) : null}
                  {status?.towers ? <SiglipStatus towers={status.towers} /> : null}
                </div>
              );
            })}
          {!loading && !profiles.some((p) => p.kind === kind) ? (
            <ResourceEmpty>{t('emptyModels')}</ResourceEmpty>
          ) : null}
        </div>
        {inventory.filter((i) => i.kind === kind).length ? (
          <>
            <h3>{t('inventory')}</h3>
            {inventory
              .filter((i) => i.kind === kind)
              .map((item) => (
                <div className="model-row" key={item.model_ref}>
                  <code>{item.model_ref}</code>
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          aria-label={t('addModel')}
                          onClick={() => {
                            const value = newModel(kind);
                            setModel({
                              value: { ...value, name: item.name, model_ref: item.model_ref,
                                source: value.source ?? localSource() },
                            });
                          }}
                        />
                      }
                    >
                      <Plus data-icon="inline-start" />
                    </TooltipTrigger>
                    <TooltipContent>{t('addModel')}</TooltipContent>
                  </Tooltip>
                </div>
              ))}
          </>
        ) : null}
      </>
      <Dialog
        open={activeView && processLog !== null}
        onOpenChange={(open) => {
          if (!open) (() => setProcessLog(null))();
        }}
      >
        <DialogContent className="sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{processLog?.title ?? t('processLog')}</DialogTitle>
          </DialogHeader>
          <div className="min-h-0 overflow-y-auto overscroll-contain">
            <pre className="runtime-log">{processLog?.text || t('emptyLog')}</pre>
          </div>
        </DialogContent>
      </Dialog>
      <ProfileEditor
        model={model}
        setModel={setModel}
        run={run}
        busy={busy}
        feedback={feedback}
        setError={setError}
      />
    </>
  );
}
