import { Activity, Copy, KeyRound, Pencil, Play, Plus, RefreshCw, Save, Square, Trash2 } from 'lucide-react';
import { cloneElement, useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, ApiError } from '../../api/client';
import { useModelsStore } from '../../store/useModelsStore';
import type { ModelInput, ModelKind, ModelInventoryItem, ProviderInput } from '../../types';
import { AppModal } from '../ui/AppModal';

const kinds: ModelKind[] = ['llm', 'embedding', 'reranker', 'image_embedding', 'vision'];
const newModel = (kind: ModelKind): ModelInput => ({
  name: '', alias: '', kind, model_ref: '', provider_profile_id: null, enabled: true, external_enabled: false,
  capabilities: { streaming: kind === 'llm', tools: false, vision: false, json_object: false, json_schema: false },
  parameters: {}, lifecycle: { unload: 'manual', idle_seconds: 300 },
});
const newProvider = (): ProviderInput => ({ name: '', protocol: 'openai_compatible', base_url: 'http://127.0.0.1:1234/v1',
  timeout_seconds: 60, concurrency: 1, queue_size: 32, queue_timeout_seconds: 30, enabled: true });

export function ModelsPanel() {
  const { t } = useTranslation('llm');
  const { profiles, providers, settings, statuses, loading, error: loadError, reload, setStatus } = useModelsStore();
  const [tab, setTab] = useState<'profiles' | 'providers' | 'service'>('profiles');
  const [kind, setKind] = useState<ModelKind>('llm');
  const [model, setModel] = useState<{ id?: string; value: ModelInput } | null>(null);
  const [provider, setProvider] = useState<{ id?: string; value: ProviderInput } | null>(null);
  const [inventory, setInventory] = useState<ModelInventoryItem[]>([]);
  const [remoteModels, setRemoteModels] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [apiKey, setApiKey] = useState('');

  useEffect(() => { void reload().catch(() => undefined); }, [reload]);
  useEffect(() => {
    let cancelled = false;
    setRemoteModels([]);
    const id = model?.value.provider_profile_id;
    if (id) void api.listProviderModels(id).then((v) => { if (!cancelled) setRemoteModels(v.models); }).catch((e) => { if (!cancelled) setError(String(e.message)); });
    return () => { cancelled = true; };
  }, [model?.value.provider_profile_id]);

  async function run(task: () => Promise<unknown>, refresh = true) {
    setBusy(true); setError(''); setNotice('');
    try { await task(); if (refresh) await reload(); setNotice(t('saved')); }
    catch (e) { setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e)); }
    finally { setBusy(false); }
  }
  const patchModel = (patch: Partial<ModelInput>) => setModel((m) => m ? { ...m, value: { ...m.value, ...patch } } : null);
  const patchParam = (key: string, value: unknown) => patchModel({ parameters: { ...model!.value.parameters, [key]: value } });
  const patchProvider = (patch: Partial<ProviderInput>) => setProvider((p) => p ? { ...p, value: { ...p.value, ...patch } } : null);
  const chatProfiles = profiles.filter((p) => p.kind === 'llm' && p.enabled);
  const statusAction = (id: string, action: 'load' | 'unload' | 'health') => run(async () => {
    try { setStatus(id, await api.modelAction(id, action)); }
    finally { setStatus(id, await api.getModelStatus(id)); }
  }, false);
  const feedback = <div role="status" className={error || loadError ? 'error-text model-feedback' : 'success-text model-feedback'}>{error || loadError || notice}</div>;

  return <section className="settings-panel models-panel" aria-busy={busy || loading}>
    <div className="model-heading"><h2>{t('title')}</h2><Icon label={t('refresh')} disabled={busy || loading} onClick={() => void run(reload, false)}><RefreshCw size={16} /></Icon></div>
    {feedback}
    <div className="model-defaults">
      <Field label={t('defaultModel')}><select aria-label={t('defaultModel')} value={settings?.default_model_profile_id || ''} disabled={busy || !settings} onChange={(e) => void run(() => api.updateModelSettings({ default_model_profile_id: e.target.value || null }))}><option value="">{t('unconfigured')}</option>{chatProfiles.map((p) => <option value={p.id} key={p.id}>{p.name}</option>)}</select></Field>
      <Field label={t('utilityModel')}><select aria-label={t('utilityModel')} value={settings?.utility_model_profile_id || ''} disabled={busy || !settings} onChange={(e) => void run(() => api.updateModelSettings({ utility_model_profile_id: e.target.value || null }))}><option value="">{t('unconfigured')}</option>{chatProfiles.map((p) => <option value={p.id} key={p.id}>{p.name}</option>)}</select></Field>
    </div>
    <div className="model-tabs" role="tablist">{(['profiles', 'providers', 'service'] as const).map((v) => <button role="tab" aria-selected={tab === v} key={v} onClick={() => setTab(v)}>{t(v)}</button>)}</div>
    {tab === 'profiles' ? <>
      <div className="model-toolbar"><select aria-label={t('kind')} value={kind} onChange={(e) => setKind(e.target.value as ModelKind)}>{kinds.map((k) => <option key={k} value={k}>{t('kinds.' + k)}</option>)}</select><div className="model-actions"><Icon label={t('inventory')} disabled={busy} onClick={() => void run(async () => setInventory(await api.listModelInventory(kind)), false)}><RefreshCw size={16} /></Icon><button className="secondary-button" disabled={busy} onClick={() => { setError(''); setModel({ value: newModel(kind) }); }}><Plus size={16} />{t('addModel')}</button></div></div>
      <div className="model-list">
        {profiles.filter((p) => p.kind === kind).map((p) => {
          const status = statuses[p.id];
          return <div className="model-row" key={p.id}>
            <div className="model-identity"><strong>{p.name}</strong><code>{p.alias}</code><small>{p.model_ref}</small></div>
            <div className="model-state"><span className={'state-' + (status?.state || 'unknown')}>{p.enabled ? t('states.' + (status?.state || 'unknown')) : t('disabled')}</span><small>{t('residency')}: {t('residencies.' + (status?.residency || 'unknown'))}</small><small>{t('active')}: {status?.active || 0} / {t('queued')}: {status?.queued || 0}</small></div>
            <div className="model-actions">
              <Icon label={t('health')} disabled={busy || !p.enabled || !p.provider_profile_id} onClick={() => void statusAction(p.id, 'health')}><Activity size={15} /></Icon>
              <Icon label={t('load')} disabled={busy || !p.enabled || !p.provider_profile_id} onClick={() => void statusAction(p.id, 'load')}><Play size={15} /></Icon>
              <Icon label={status?.unload_supported ? t('unload') : t('unloadUnsupported')} disabled={busy || !status?.unload_supported || !!status.active || !!status.queued} onClick={() => void statusAction(p.id, 'unload')}><Square size={14} /></Icon>
              <Icon label={t('edit')} disabled={busy} onClick={() => { const { id, created_at: _c, updated_at: _u, ...value } = p; setError(''); setModel({ id, value }); }}><Pencil size={15} /></Icon>
              <Icon label={t('duplicate')} disabled={busy} onClick={() => { const { id: _id, created_at: _c, updated_at: _u, ...value } = p; setError(''); setModel({ value: { ...value, alias: p.alias + '-copy', name: p.name + ' ' + t('copy') } }); }}><Copy size={15} /></Icon>
              <Icon label={t('delete')} disabled={busy} onClick={() => void run(() => api.deleteModelProfile(p.id))}><Trash2 size={15} /></Icon>
            </div>
          </div>;
        })}
        {!loading && !profiles.some((p) => p.kind === kind) ? <p className="model-empty">{t('emptyModels')}</p> : null}
      </div>
      {inventory.filter((i) => i.kind === kind).length ? <><h3>{t('inventory')}</h3>{inventory.filter((i) => i.kind === kind).map((item) => <div className="model-row" key={item.model_ref}><code>{item.model_ref}</code><Icon label={t('addModel')} onClick={() => setModel({ value: { ...newModel(kind), name: item.name, model_ref: item.model_ref } })}><Plus size={16} /></Icon></div>)}</> : null}
    </> : null}
    {tab === 'providers' ? <>
      <div className="model-toolbar"><span>OpenAI Compatible</span><button className="secondary-button" disabled={busy} onClick={() => { setError(''); setProvider({ value: newProvider() }); }}><Plus size={16} />{t('addProvider')}</button></div>
      {providers.map((p) => <div className="model-row" key={p.id}><div className="model-identity"><strong>{p.name}</strong><small>{p.base_url}</small><small>{p.enabled ? t('enabled') : t('disabled')}</small></div><div className="model-actions"><Icon label={t('edit')} disabled={busy} onClick={() => { const { id, created_at: _c, updated_at: _u, has_api_key: _k, ...value } = p; setError(''); setProvider({ id, value }); }}><Pencil size={16} /></Icon><Icon label={t('delete')} disabled={busy} onClick={() => void run(() => api.deleteProviderProfile(p.id))}><Trash2 size={16} /></Icon></div></div>)}
      {!providers.length && !loading ? <p className="model-empty">{t('emptyProviders')}</p> : null}
    </> : null}
    {tab === 'service' && settings ? <div className="model-service">
      <Check label={t('externalEnabled')} checked={settings.external_enabled} disabled={busy} onChange={(external_enabled) => void run(() => api.updateModelSettings({ external_enabled }))} />
      <Field label={t('apiKey')}><div className="model-actions"><input aria-label={t('apiKey')} type="password" autoComplete="new-password" placeholder={settings.has_external_api_key ? t('keySet') : ''} value={apiKey} onChange={(e) => setApiKey(e.target.value)} /><Icon label={t('generateKey')} onClick={() => setApiKey(crypto.randomUUID() + crypto.randomUUID())}><KeyRound size={16} /></Icon><Icon label={t('copy')} disabled={!apiKey} onClick={() => void run(() => navigator.clipboard.writeText(apiKey), false)}><Copy size={16} /></Icon><Icon label={t('save')} disabled={!apiKey || busy} onClick={() => void run(async () => { await api.updateModelSettings({ external_api_key: apiKey }); setApiKey(''); })}><Save size={16} /></Icon></div></Field>
      <NumberInput label={t('bodyLimit')} value={settings.max_request_mb} min={1} max={100} onChange={(v) => { if (v != null) void run(() => api.updateModelSettings({ max_request_mb: v })); }} />
    </div> : null}
    <AppModal open={!!model} title={model?.id ? t('editModel') : t('addModel')} closeLabel={t('close')} width="large" onClose={() => { if (!busy) setModel(null); }}>
      {model ? <form onSubmit={(e) => { e.preventDefault(); void run(async () => { if (model.id) await api.patchModelProfile(model.id, model.value); else await api.createModelProfile(model.value); setModel(null); }); }}>
        {feedback}<fieldset disabled={busy} className="model-form"><div className="model-form-grid">
          <Field label={t('name')}><input required value={model.value.name} onChange={(e) => patchModel({ name: e.target.value })} /></Field>
          <Field label={t('alias')}><input required pattern="[a-z0-9][a-z0-9._-]{0,127}" value={model.value.alias} onChange={(e) => patchModel({ alias: e.target.value })} /></Field>
          <Field label={t('kind')}><select disabled value={model.value.kind}>{kinds.map((k) => <option value={k} key={k}>{t('kinds.' + k)}</option>)}</select></Field>
          <Field label={t('provider')}><select value={model.value.provider_profile_id || ''} onChange={(e) => patchModel({ provider_profile_id: e.target.value || null })}><option value="">{t('unavailableBackend')}</option>{providers.map((p) => <option value={p.id} key={p.id}>{p.name}</option>)}</select></Field>
          <Field label={t('modelRef')}><input required list="provider-models" value={model.value.model_ref} onChange={(e) => patchModel({ model_ref: e.target.value })} /></Field>
          <datalist id="provider-models">{remoteModels.map((id) => <option key={id} value={id} />)}</datalist>
          <div className="model-checks"><Check label={t('enabled')} checked={model.value.enabled} onChange={(enabled) => patchModel({ enabled })} /><Check label={t('externalModel')} checked={model.value.external_enabled} onChange={(external_enabled) => patchModel({ external_enabled })} /></div>
        </div>
        {model.value.kind === 'llm' ? <><h3>{t('capabilities')}</h3><div className="model-checks">{(Object.keys(model.value.capabilities) as Array<keyof ModelInput['capabilities']>).map((key) => <Check key={key} label={t('cap.' + key)} checked={model.value.capabilities[key]} onChange={(v) => patchModel({ capabilities: { ...model.value.capabilities, [key]: v } })} />)}</div></> : null}
        <h3>{t('parameters')}</h3><div className="model-form-grid">
          {model.value.kind === 'llm' ? <>
            {[['temperature', 0, 2, 0.1], ['top_p', 0, 1, 0.05], ['max_tokens', 1, undefined, 1], ['presence_penalty', -2, 2, 0.1], ['frequency_penalty', -2, 2, 0.1], ['seed', undefined, undefined, 1]].map(([key, min, max, step]) => <NumberInput key={String(key)} label={t('params.' + key)} value={model.value.parameters[String(key)] as number | undefined} min={min as number} max={max as number} step={step as number} onChange={(v) => patchParam(String(key), v)} />)}
            <Field label={t('params.stop')}><input value={String(model.value.parameters.stop || '')} onChange={(e) => patchParam('stop', e.target.value || null)} /></Field>
          </> : <>
            <NumberInput label={t('params.batch_size')} value={Number(model.value.parameters.batch_size || (model.value.kind === 'embedding' || model.value.kind === 'reranker' ? 16 : 1))} min={1} onChange={(v) => patchParam('batch_size', v ?? 1)} />
            {['embedding', 'image_embedding'].includes(model.value.kind) ? <><NumberInput label={t('params.dimensions')} value={model.value.parameters.dimensions as number | undefined} min={1} onChange={(v) => patchParam('dimensions', v)} /><Check label={t('params.normalize')} checked={model.value.parameters.normalize !== false} onChange={(v) => patchParam('normalize', v)} /></> : null}
            {model.value.kind === 'embedding' ? <>{['document_instruction', 'query_instruction'].map((key) => <Field key={key} label={t('params.' + key)}><textarea rows={2} value={String(model.value.parameters[key] || '')} onChange={(e) => patchParam(key, e.target.value)} /></Field>)}</> : null}
            {model.value.kind === 'image_embedding' || model.value.kind === 'vision' ? <Field label={t('params.architecture')}><select value={String(model.value.parameters.architecture || (model.value.kind === 'vision' ? 'florence2' : 'clip'))} onChange={(e) => patchParam('architecture', e.target.value)}>{(model.value.kind === 'vision' ? ['florence2', 'wd14'] : ['clip', 'siglip2', 'dinov2']).map((v) => <option key={v} value={v}>{v}</option>)}</select></Field> : null}
            {model.value.kind === 'vision' ? <Field label={t('params.task')}><input value={String(model.value.parameters.task || 'caption')} onChange={(e) => patchParam('task', e.target.value)} /></Field> : null}
          </>}
        </div><h3>{t('lifecycle')}</h3><div className="model-form-grid"><Field label={t('release')}><select value={model.value.lifecycle.unload} onChange={(e) => patchModel({ lifecycle: { ...model.value.lifecycle, unload: e.target.value as ModelInput['lifecycle']['unload'] } })}>{(['manual', 'after_request', 'idle'] as const).map((v) => <option value={v} key={v}>{t('policy.' + v)}</option>)}</select></Field>{model.value.lifecycle.unload === 'idle' ? <NumberInput label={t('idleSeconds')} value={model.value.lifecycle.idle_seconds} min={1} onChange={(v) => patchModel({ lifecycle: { ...model.value.lifecycle, idle_seconds: v ?? 300 } })} /> : null}</div>
        <div className="model-form-footer"><button type="submit" className="primary-button"><Save size={16} />{t('save')}</button></div></fieldset>
      </form> : null}
    </AppModal>
    <AppModal open={!!provider} title={provider?.id ? t('editProvider') : t('addProvider')} closeLabel={t('close')} onClose={() => { if (!busy) setProvider(null); }}>
      {provider ? <form onSubmit={(e) => { e.preventDefault(); void run(async () => { if (provider.id) await api.patchProviderProfile(provider.id, provider.value); else await api.createProviderProfile(provider.value); setProvider(null); }); }}>{feedback}<fieldset disabled={busy} className="model-form">
        <Field label={t('name')}><input required value={provider.value.name} onChange={(e) => patchProvider({ name: e.target.value })} /></Field>
        <Field label={t('baseUrl')}><input required type="url" value={provider.value.base_url} onChange={(e) => patchProvider({ base_url: e.target.value })} /></Field>
        <Field label={t('apiKey')}><input type="password" autoComplete="new-password" value={provider.value.api_key ?? ''} placeholder={providers.find((p) => p.id === provider.id)?.has_api_key ? t('keySet') : ''} onChange={(e) => patchProvider({ api_key: e.target.value })} /></Field>
        <div className="model-form-grid">{(['timeout_seconds', 'concurrency', 'queue_size', 'queue_timeout_seconds'] as const).map((key) => <NumberInput key={key} label={t('connection.' + key)} value={provider.value[key]} min={key === 'queue_size' ? 0 : 1} onChange={(v) => patchProvider({ [key]: v ?? 1 })} />)}</div>
        <Check label={t('enabled')} checked={provider.value.enabled} onChange={(enabled) => patchProvider({ enabled })} /><div className="model-form-footer"><button className="primary-button" type="submit"><Save size={16} />{t('save')}</button></div>
      </fieldset></form> : null}
    </AppModal>
  </section>;
}

function Field({ label, children }: { label: string; children: React.ReactElement<{ id?: string }> }) {
  const id = useId();
  return <div className="settings-field"><label htmlFor={id}>{label}</label>{cloneElement(children, { id })}</div>;
}
function Check({ label, checked, onChange, disabled }: { label: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) { return <label className="settings-toggle"><input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} /><span>{label}</span></label>; }
function Icon({ label, children, disabled, onClick }: { label: string; children: React.ReactNode; disabled?: boolean; onClick: () => void }) { return <span title={label} className="model-icon-wrap"><button type="button" className="icon-button" aria-label={label} disabled={disabled} onClick={onClick}>{children}</button></span>; }
function NumberInput({ label, value, min, max, step = 1, onChange }: { label: string; value?: number | null; min?: number; max?: number; step?: number; onChange: (v: number | null) => void }) { return <Field label={label}><input type="number" value={value ?? ''} min={min} max={max} step={step} onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} /></Field>; }
