import { Download, FileText, RefreshCw, Save, Square, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../api/models';
import { useModelsStore } from '../../store/useModelsStore';
import type { RuntimeDownloadSettings, RuntimeJob } from '../../types/models';
import { AppModal } from '../ui/AppModal';
import { CacheJobResult, RuntimeStoragePanel } from './RuntimeStoragePanel';
import { runtimeFamilyKey, runtimeBuild } from './models/profileDefaults';

export function RuntimesPanel() {
  const { t } = useTranslation('llm');
  const { catalog, installations, jobs, runtimeLoading, runtimeError, reloadRuntimes, reloadStorage, storageLoading, setJob } = useModelsStore();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [settings, setSettings] = useState<RuntimeDownloadSettings | null>(null);
  const [log, setLog] = useState<{ job: RuntimeJob; text: string } | null>(null);
  const active = jobs.find((job) => job.state === 'queued' || job.state === 'running');
  const jobLabel = (job: RuntimeJob) => job.runtime_id
    ? `${t('runtimeFamilies.' + runtimeFamilyKey(job.runtime_id, job.variant!))} / ${runtimeBuild(job.variant!)} / ${t('runtimeOperations.' + job.operation)}`
    : t('runtimeOperations.' + job.operation);
  useEffect(() => {
    void modelsApi
      .runtimeSettings()
      .then(setSettings)
      .catch((e) => setError(String(e.message)));
  }, []);
  async function run(task: () => Promise<unknown>) {
    setBusy(true);
    setError('');
    try {
      await task();
      await reloadRuntimes();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function showLog(job: RuntimeJob) {
    const value = await modelsApi.runtimeJobLog(job.id);
    setLog({ job, text: value.text });
  }
  return (
    <div className="runtime-panel">
      <div className="model-toolbar">
        <h3>{t('runtimes')}</h3>
        <button
          className="icon-button"
          title={t('refresh')}
          aria-label={t('refresh')}
          disabled={busy || runtimeLoading || storageLoading}
          onClick={() => void run(reloadStorage)}
        >
          <RefreshCw size={16} />
        </button>
      </div>
      {error || runtimeError ? (
        <p role="alert" className="error-text">
          {error || runtimeError}
        </p>
      ) : null}
      <RuntimeStoragePanel busy={busy} active={active}
        onCleanup={(mode) => run(async () => setJob(await modelsApi.cleanupRuntimeCache(mode)))}
        onCancel={(job) => void run(async () => setJob(await modelsApi.cancelRuntimeJob(job.id)))} />
      {catalog.map((entry) => {
        const installation = installations.find((item) => item.id === `${entry.runtime_id}/${entry.variant}`);
        const job = jobs.find((item) => item.runtime_id === entry.runtime_id && item.variant === entry.variant);
        const running = job?.state === 'queued' || job?.state === 'running';
        const state = installation?.state || (entry.supported ? 'not_installed' : 'unsupported');
        return (
          <div className="runtime-row" key={`${entry.runtime_id}/${entry.variant}`}>
            <div className="model-identity">
              <strong>{t('runtimeFamilies.' + runtimeFamilyKey(entry.runtime_id, entry.variant))}</strong>
              <code>{runtimeBuild(entry.variant)}</code>
              <small>
                {entry.version === 'pending' ? t('runtimePendingVersion') : entry.version} / {entry.platform} / {entry.architecture}
              </small>
            </div>
            <div className="runtime-progress">
              <span>{t(entry.reason === 'RUNTIME_NOT_IMPLEMENTED' ? 'runtimeNotImplemented' : 'runtimeStates.' + state)}</span>
              {job ? (
                <small>
                  {t('jobStates.' + job.state)}: {t('runtimeStages.' + job.stage)}
                </small>
              ) : null}
              {running ? (
                <progress
                  aria-label={t('runtimeProgress')}
                  value={job.progress_total ? job.progress_current : undefined}
                  max={job.progress_total || undefined}
                />
              ) : null}
              {installation?.error_code || job?.error_code ? (
                <code className="error-text">{installation?.error_code || job?.error_code}</code>
              ) : null}
            </div>
            <div className="model-actions">
              {running ? (
                <button
                  type="button"
                  className="icon-button"
                  title={t('cancelInstall')}
                  aria-label={t('cancelInstall')}
                  disabled={busy || job.cancel_requested}
                  onClick={() => void run(async () => setJob(await modelsApi.cancelRuntimeJob(job.id)))}
                >
                  <Square size={16} />
                </button>
              ) : (
                <button
                  type="button"
                  className="icon-button"
                  title={t(state === 'broken' || state === 'interrupted' ? 'retryInstall' : 'installRuntime')}
                  aria-label={t(state === 'broken' || state === 'interrupted' ? 'retryInstall' : 'installRuntime')}
                  disabled={busy || !!active || !entry.supported || state === 'installed'}
                  onClick={() =>
                    void run(async () =>
                      setJob(await modelsApi.runtimeAction(entry.runtime_id, entry.variant, 'install')),
                    )
                  }
                >
                  <Download size={16} />
                </button>
              )}
              <button
                type="button"
                className="icon-button"
                title={t('uninstallRuntime')}
                aria-label={t('uninstallRuntime')}
                disabled={busy || !!active || !entry.supported || state === 'not_installed'}
                onClick={() =>
                  void run(async () =>
                    setJob(await modelsApi.runtimeAction(entry.runtime_id, entry.variant, 'uninstall')),
                  )
                }
              >
                <Trash2 size={16} />
              </button>
              <button
                type="button"
                className="icon-button"
                title={t('runtimeLog')}
                aria-label={t('runtimeLog')}
                disabled={busy || !job}
                onClick={() => job && void run(() => showLog(job))}
              >
                <FileText size={16} />
              </button>
            </div>
          </div>
        );
      })}
      <details className="runtime-download-settings">
        <summary>{t('downloadSettings')}</summary>
        {settings ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void run(async () => setSettings(await modelsApi.patchRuntimeSettings(settings)));
            }}
          >
            <fieldset className="model-form" disabled={busy || !!active}>
              {(Object.keys(settings) as Array<keyof RuntimeDownloadSettings>).map((key) => (
                <label key={key} className="settings-field">
                  <span>{t('download.' + key)}</span>
                  <input
                    type="url"
                    value={settings[key] || ''}
                    onChange={(e) => setSettings({ ...settings, [key]: e.target.value || null })}
                  />
                </label>
              ))}
              <div className="model-form-footer">
                <button type="submit" className="primary-button">
                  <Save size={16} />
                  {t('save')}
                </button>
              </div>
            </fieldset>
          </form>
        ) : null}
      </details>
      {jobs.length ? (
        <details>
          <summary>{t('runtimeHistory')}</summary>
          <div className="runtime-history">
            {jobs.map((job) => (
              <div className="model-row" key={job.id}>
                <span>
                  {jobLabel(job)}
                  <small>{new Date(job.created_at).toLocaleString()}</small>
                </span>
                <span>{t('jobStates.' + job.state)}</span>
                <button
                  type="button"
                  className="icon-button"
                  aria-label={t('runtimeLog')}
                  title={t('runtimeLog')}
                  disabled={busy}
                  onClick={() => void run(() => showLog(job))}
                >
                  <FileText size={16} />
                </button>
              </div>
            ))}
          </div>
        </details>
      ) : null}
      <AppModal open={!!log} title={t('runtimeLog')} width="large" closeLabel={t('close')} onClose={() => setLog(null)}>
        {log ? (
          <>
            <div className="model-toolbar">
              <span>{jobLabel(log.job)}</span>
              <button
                className="icon-button"
                title={t('refresh')}
                aria-label={t('refresh')}
                disabled={busy}
                onClick={() => void run(() => showLog(log.job))}
              >
                <RefreshCw size={16} />
              </button>
            </div>
            <CacheJobResult job={jobs.find((job) => job.id === log.job.id) || log.job} />
            <pre className="runtime-log">{log.text || t('emptyLog')}</pre>
          </>
        ) : null}
      </AppModal>
    </div>
  );
}
