import { Pencil, Plus, Settings2, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { modelsApi } from '../../../api/models';
import { useModelsStore } from '../../../store/useModelsStore';
import { LocalBackendPanel } from '../LocalBackendPanel';
import { Icon } from './fields';
import type { ModelFeedbackProps } from './types';
import { newBackend } from './profileDefaults';
import { BackendEditor, type BackendDraft } from './BackendEditor';

export function BackendsTab({ run, busy, feedback, setError, active }: ModelFeedbackProps & { active: boolean }) {
  const { t } = useTranslation('llm');
  const { backends } = useModelsStore();
  const [backend, setBackend] = useState<BackendDraft | null>(null);
  const [showLocal, setShowLocal] = useState(true);
  return (
    <>
      <div className="model-toolbar">
        <h3>{t('backends')}</h3>
        <button className="secondary-button" disabled={busy} onClick={() => {
          setError(''); setBackend({ value: newBackend() });
        }}><Plus size={16} />{t('addBackend')}</button>
      </div>
      {[...backends].sort((a, b) => Number(b.type === 'local') - Number(a.type === 'local')).map((item) => (
        <div className="model-row" key={item.id}>
          <div className="model-identity">
            <strong>{item.type === 'local' ? t('localBackend') : item.name}</strong>
            <small>{item.type === 'local' ? t('localBackendSummary') : item.connection?.base_url}</small>
            <small>{item.enabled ? t('enabled') : t('disabled')}</small>
          </div>
          <div className="model-actions">
            {item.type === 'local' ? (
              <Icon label={t('manageBackend')} onClick={() => setShowLocal(!showLocal)}><Settings2 size={16} /></Icon>
            ) : <>
              <Icon label={t('edit')} disabled={busy} onClick={() => {
                const { has_api_key: _key, ...connection } = item.connection!;
                setError('');
                setBackend({ id: item.id, value: { name: item.name, type: 'openai_compatible', enabled: item.enabled, connection, download: null } });
              }}><Pencil size={16} /></Icon>
              <Icon label={t('delete')} disabled={busy} onClick={() => void run(() => modelsApi.deleteBackendProfile(item.id))}>
                <Trash2 size={16} />
              </Icon>
            </>}
          </div>
        </div>
      ))}
      <div hidden={!showLocal}><LocalBackendPanel activeView={active && showLocal} /></div>
      <BackendEditor backend={backend} setBackend={setBackend} run={run} busy={busy} feedback={feedback} setError={setError} />
    </>
  );
}
