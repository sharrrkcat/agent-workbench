import { Activity, Copy, FileText, Pencil, Play, Plus, RefreshCw, Square, Trash2 } from 'lucide-react';
import { useState } from 'react';

import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import { useModelsStore } from '../../../store/useModelsStore';
import type { ModelKind, ModelInventoryItem } from '../../../types/models';
import { AppModal } from '../../ui/AppModal';
import { Icon } from './fields';
import type { ModelFeedbackProps } from './types';
import { kinds, newModel } from './profileDefaults';
import { ProfileEditor, type ProfileDraft } from './ProfileEditor';

export function ProfilesTab({
  run,
  busy,
  feedback,
  setError,
  onOpenRuntimes,
}: ModelFeedbackProps & { onOpenRuntimes: () => void }) {
  const { t } = useTranslation('llm');
  const { profiles, statuses, setStatus, loading } = useModelsStore();
  const [kind, setKind] = useState<ModelKind>('llm');
  const [model, setModel] = useState<ProfileDraft | null>(null);
  const [inventory, setInventory] = useState<ModelInventoryItem[]>([]);
  const [processLog, setProcessLog] = useState<string | null>(null);
  const statusAction = (id: string, action: 'load' | 'unload' | 'health') =>
    run(async () => {
      try {
        setStatus(id, await modelsApi.modelAction(id, action));
      } finally {
        setStatus(id, await modelsApi.getModelStatus(id));
      }
    }, false);
  return (
    <>
      <>
        <div className="model-toolbar">
          <select aria-label={t('kind')} value={kind} onChange={(e) => setKind(e.target.value as ModelKind)}>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {t('kinds.' + k)}
              </option>
            ))}
          </select>
          <div className="model-actions">
            <Icon
              label={t('inventory')}
              disabled={busy}
              onClick={() => void run(async () => setInventory(await modelsApi.listModelInventory(kind)), false)}
            >
              <RefreshCw size={16} />
            </Icon>
            <button
              className="secondary-button"
              disabled={busy}
              onClick={() => {
                setError('');
                setModel({ value: newModel(kind) });
              }}
            >
              <Plus size={16} />
              {t('addModel')}
            </button>
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
                  </div>
                  <div className="model-state">
                    <span className={'state-' + (status?.state || 'unknown')}>
                      {p.enabled ? t('states.' + (status?.state || 'unknown')) : t('disabled')}
                    </span>
                    <small>
                      {t('residency')}: {t('residencies.' + (status?.residency || 'unknown'))}
                    </small>
                    <small>
                      {t('active')}: {status?.active || 0} / {t('queued')}: {status?.queued || 0}
                    </small>
                  </div>
                  <div className="model-actions">
                    <Icon
                      label={t('health')}
                      disabled={busy || !p.enabled || !(p.provider_profile_id || p.runtime_id)}
                      onClick={() => void statusAction(p.id, 'health')}
                    >
                      <Activity size={15} />
                    </Icon>
                    <Icon
                      label={t('load')}
                      disabled={busy || !p.enabled || !(p.provider_profile_id || p.runtime_id)}
                      onClick={() => void statusAction(p.id, 'load')}
                    >
                      <Play size={15} />
                    </Icon>
                    <Icon
                      label={status?.unload_supported ? t('unload') : t('unloadUnsupported')}
                      disabled={
                        busy ||
                        !status?.unload_supported ||
                        !!status.active ||
                        !!status.queued ||
                        (!!status.runtime && status.runtime.install_state !== 'installed')
                      }
                      onClick={() => void statusAction(p.id, 'unload')}
                    >
                      <Square size={14} />
                    </Icon>
                    {p.runtime_id ? (
                      <Icon
                        label={t('processLog')}
                        disabled={busy}
                        onClick={() =>
                          void run(async () => setProcessLog((await modelsApi.getModelLog(p.id)).text), false)
                        }
                      >
                        <FileText size={14} />
                      </Icon>
                    ) : null}
                    <Icon
                      label={t('edit')}
                      disabled={busy}
                      onClick={() => {
                        const { id, created_at: _c, updated_at: _u, ...value } = p;
                        setError('');
                        setModel({ id, value });
                      }}
                    >
                      <Pencil size={15} />
                    </Icon>
                    <Icon
                      label={t('duplicate')}
                      disabled={busy}
                      onClick={() => {
                        const { id: _id, created_at: _c, updated_at: _u, ...value } = p;
                        setError('');
                        setModel({ value: { ...value, alias: p.alias + '-copy', name: p.name + ' ' + t('copy') } });
                      }}
                    >
                      <Copy size={15} />
                    </Icon>
                    <Icon
                      label={t('delete')}
                      disabled={busy}
                      onClick={() => void run(() => modelsApi.deleteModelProfile(p.id))}
                    >
                      <Trash2 size={15} />
                    </Icon>
                  </div>
                  {status?.runtime ? (
                    <div className="model-runtime-state">
                      <span>
                        {status.runtime.runtime_id} / {status.runtime.variant} / {status.runtime.version}:{' '}
                        {t('runtimeStates.' + status.runtime.install_state)}
                      </span>
                      {status.runtime.device_name ? <span>{status.runtime.device_name}</span> : null}
                      {status.runtime.gpu_layers_loaded != null ? <span>{t('gpuOffloaded', {
                        loaded: status.runtime.gpu_layers_loaded, total: status.runtime.gpu_layers_total,
                      })}</span> : null}
                      {status.error_code ? <code className="error-text">{status.error_code}</code> : null}
                      {status.runtime.install_state !== 'installed' ? (
                        <button type="button" className="text-button" onClick={() => onOpenRuntimes()}>
                          {t('manageRuntime')}
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              );
            })}
          {!loading && !profiles.some((p) => p.kind === kind) ? (
            <p className="model-empty">{t('emptyModels')}</p>
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
                  <Icon
                    label={t('addModel')}
                    onClick={() =>
                      setModel({ value: { ...newModel(kind), name: item.name, model_ref: item.model_ref } })
                    }
                  >
                    <Plus size={16} />
                  </Icon>
                </div>
              ))}
          </>
        ) : null}
      </>
      <AppModal
        open={processLog !== null}
        title={t('processLog')}
        closeLabel={t('close')}
        width="large"
        onClose={() => setProcessLog(null)}
      >
        <pre className="runtime-log">{processLog || t('emptyLog')}</pre>
      </AppModal>
      <ProfileEditor model={model} setModel={setModel} run={run} busy={busy} feedback={feedback} setError={setError} />
    </>
  );
}
