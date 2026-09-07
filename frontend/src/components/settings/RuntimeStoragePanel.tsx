import { BrushCleaning, Square, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useModelsStore } from '../../store/useModelsStore';
import type { RuntimeJob } from '../../types/models';
import { AppModal } from '../ui/AppModal';

export function runtimeBytes(value: number | null | undefined, unknown: string) {
  if (value == null) return unknown;
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  const exponent = value > 0 ? Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1) : 0;
  return `${(value / 1024 ** exponent).toLocaleString(undefined, { maximumFractionDigits: exponent ? 2 : 0 })} ${units[exponent]}`;
}

export function CacheJobResult({ job }: { job: RuntimeJob }) {
  const { t } = useTranslation('llm');
  if (!job.result) return null;
  return (
    <dl className="runtime-cache-result">
      {(['before', 'after'] as const).map((moment) => (
        <div key={moment}>
          <dt>{t('storage.' + moment)}</dt>
          <dd>{runtimeBytes(job.result?.[moment]?.logical_bytes, t('storage.unknown'))}</dd>
          <dt>{t('storage.exclusive')}</dt>
          <dd>{runtimeBytes(job.result?.[moment]?.exclusive_bytes, t('storage.unknown'))}</dd>
        </div>
      ))}
    </dl>
  );
}

export function RuntimeStoragePanel({ busy, active, onCleanup, onCancel }: {
  busy: boolean;
  active: RuntimeJob | undefined;
  onCleanup: (mode: 'prune' | 'clean') => Promise<void>;
  onCancel: (job: RuntimeJob) => void;
}) {
  const { t } = useTranslation('llm');
  const { storage, storageLoading, storageError, reloadStorage, jobs } = useModelsStore();
  const [confirm, setConfirm] = useState(false);
  const terminal = jobs.find((job) => job.state !== 'queued' && job.state !== 'running');
  const terminalKey = terminal ? `${terminal.id}:${terminal.revision}` : '';
  useEffect(() => { void reloadStorage().catch(() => undefined); }, [reloadStorage, terminalKey]);
  const cache = storage?.groups.find((group) => group.category === 'cache');
  const latestCache = jobs.find((job) => job.operation === 'cache_prune' || job.operation === 'cache_clean');
  const bytes = (value: number | null | undefined) => runtimeBytes(value, t('storage.unknown'));
  return (
    <section className="runtime-storage" aria-label={t('storage.title')} aria-busy={storageLoading}>
      <div className="runtime-storage-heading">
        <h3>{t('storage.title')}</h3>
        <small>{storageLoading ? t('storage.scanning') : storage ? new Date(storage.scanned_at).toLocaleString() : t('storage.unavailable')}</small>
      </div>
      {storageError ? <p className="error-text" role="alert">{storageError}</p> : null}
      {storage && !storage.complete ? <p className="runtime-storage-warning" role="status">{t('storage.incomplete')}</p> : null}
      <dl className="runtime-storage-summary">
        <div><dt>{t('storage.totalUnique')}</dt><dd>{bytes(storage?.totals.unique_bytes)}</dd></div>
        <div><dt>{t('storage.cacheSize')}</dt><dd>{bytes(cache?.logical_bytes)}</dd></div>
        <div><dt title={t('storage.estimateHint')}>{t('storage.reclaimable')}</dt><dd>{bytes(cache?.exclusive_bytes)}</dd></div>
      </dl>
      <div className="runtime-cache-actions">
        <button type="button" className="secondary-button" disabled={busy || !!active} onClick={() => void onCleanup('prune')}>
          <BrushCleaning size={16} />{t('cachePrune')}
        </button>
        <button type="button" className="secondary-button" disabled={busy || !!active} onClick={() => setConfirm(true)}>
          <Trash2 size={16} />{t('cacheClean')}
        </button>
      </div>
      {latestCache ? (
        <div className="runtime-cache-task" role="status">
          <div className="runtime-cache-task-heading">
            <span>{t('runtimeOperations.' + latestCache.operation)}: {t('jobStates.' + latestCache.state)}</span>
            {active?.id === latestCache.id ? (
              <button type="button" className="icon-button" title={t('cancelTask')} aria-label={t('cancelTask')}
                disabled={busy || latestCache.cancel_requested} onClick={() => onCancel(latestCache)}><Square size={16} /></button>
            ) : null}
          </div>
          {active?.id === latestCache.id ? <span>{t('runtimeStages.' + latestCache.stage)}</span> : null}
          {latestCache.error_code ? <code className="error-text">{latestCache.error_code}</code> : null}
          <CacheJobResult job={latestCache} />
        </div>
      ) : null}
      <details className="runtime-storage-details">
        <summary>{t('storage.details')}</summary>
        {storage ? (
          <table className="runtime-storage-table">
            <thead><tr><th>{t('storage.directory')}</th>{['files', 'logical', 'unique', 'shared', 'exclusive'].map((key) => <th key={key}>{t('storage.' + key)}</th>)}</tr></thead>
            <tbody>{storage.groups.map((group) => (
              <tr key={group.id}>
                <th scope="row"><span>{group.category === 'runtime' ? `${group.runtime_id} / ${group.variant}` : t('storage.categories.' + group.category)}</span>
                  <code>{group.category === 'other' ? '' : group.relative_path}</code></th>
                <td data-label={t('storage.files')}>{group.file_count == null ? t('storage.unknown') : group.file_count.toLocaleString()}</td>
                {(['logical_bytes', 'unique_bytes', 'shared_bytes', 'exclusive_bytes'] as const).map((key) => (
                  <td key={key} data-label={t('storage.' + key.split('_')[0])}>{bytes(group[key])}</td>
                ))}
              </tr>
            ))}</tbody>
          </table>
        ) : <p>{storageLoading ? t('storage.scanning') : t('storage.unavailable')}</p>}
        {storage?.warnings.length ? <ul className="runtime-storage-warnings">{storage.warnings.map((warning, index) => (
          <li key={index}><code>{warning.relative_path}</code>: {t('storage.warnings.' + warning.code)}</li>
        ))}</ul> : null}
      </details>
      <AppModal open={confirm} title={t('cacheCleanConfirm')} closeLabel={t('close')} onClose={() => setConfirm(false)}>
        <p>{t('storage.reclaimable')}: <strong>{bytes(cache?.exclusive_bytes)}</strong></p>
        <p className="runtime-clean-consequence">{t('cacheCleanConsequence')}</p>
        <div className="model-form-footer">
          <button type="button" className="primary-button" disabled={busy || !!active} onClick={() => {
            setConfirm(false);
            void onCleanup('clean');
          }}><Trash2 size={16} />{t('cacheClean')}</button>
        </div>
      </AppModal>
    </section>
  );
}
