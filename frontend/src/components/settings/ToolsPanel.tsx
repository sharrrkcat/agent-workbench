import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../api/client';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { HarnessSettings, HarnessTool } from '../../types';
import { MessageParts } from '../MessageBubble';
import { RunPanel } from '../RunPanel';
import { Panel } from '../SettingsPage';

export function ToolsPanel() {
  const { t } = useTranslation('settings');
  const session = useWorkbenchStore((state) => state.currentSession);
  const runs = useWorkbenchStore((state) => state.runs);
  const messages = useWorkbenchStore((state) => state.messages);
  const sending = useWorkbenchStore((state) => state.sending);
  const error = useWorkbenchStore((state) => state.error);
  const callTool = useWorkbenchStore((state) => state.callTool);
  const [tools, setTools] = useState<HarnessTool[]>([]);
  const [settings, setSettings] = useState<HarnessSettings | null>(null);
  const [selected, setSelected] = useState('base64_encode');
  const [argumentsText, setArgumentsText] = useState('{"value":""}');
  const [feedback, setFeedback] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let disposed = false;
    void Promise.all([api.listTools(), api.getToolSettings()])
      .then(([catalog, value]) => { if (!disposed) { setTools(catalog); setSettings(value); } })
      .catch((error: unknown) => { if (!disposed) setFeedback(error instanceof Error ? error.message : t('failed')); });
    return () => { disposed = true; };
  }, [t]);
  useEffect(() => { setFeedback(''); }, [session?.session_id]);
  const current = tools.find((item) => item.name === selected);
  const allowed = !!current && !!session?.effective.tools_allowed.includes(current.name) && current.direct_callable;
  const active = runs.some((run) => run.session_id === session?.session_id && ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(run.status));
  const latest = [...runs].reverse().find((run) => run.session_id === session?.session_id && run.kind === 'tool' && run.metadata?.tool_name === selected);
  const output = latest ? messages.filter((message) => message.run_id === latest.run_id) : [];

  async function saveSettings() {
    if (!settings || saving) return;
    setSaving(true);
    try { const value = await api.updateToolSettings(settings); setSettings(value); setFeedback(t('saved')); }
    catch (error) { setFeedback(error instanceof Error ? error.message : t('failed')); }
    finally { setSaving(false); }
  }

  async function call() {
    if (!session || !current || !allowed || active || sending) return;
    setFeedback('');
    try {
      const args: unknown = JSON.parse(argumentsText);
      if (!args || typeof args !== 'object' || Array.isArray(args)) throw new Error(t('toolArgumentsObject'));
      const result = await callTool(current.name, args as Record<string, unknown>);
      if (result && result.run.session_id === useWorkbenchStore.getState().currentSession?.session_id) setFeedback(t(result.run.status === 'WAITING_FOR_USER' ? 'approvalRequired' : 'toolCalled'));
    } catch (error) { setFeedback(error instanceof Error ? error.message : t('failed')); }
  }

  return <Panel title={t('tools')}>
    <p className="settings-note">{t('toolDirectHelp')}</p>
    <h3>{t('toolCatalog')}</h3>
    <div className="settings-list">{tools.map((tool) => <button key={tool.name} type="button" aria-pressed={selected === tool.name} className="settings-list-row tool-selector" onClick={() => { setSelected(tool.name); setArgumentsText(exampleArguments(tool)); setFeedback(''); }}>
      <span>{tool.name}<small>{t('toolDescriptions.' + tool.name)}</small></span>
      <small>{t('toolRisk.' + tool.risk)} · {tool.requires_approval ? t('approvalRequired') : t('noApproval')}</small>
    </button>)}</div>
    {current ? <div className="tool-call-form">
      <h3>{current.name}</h3>
      <details><summary>{t('toolSchema')}</summary><pre className="part-json">{JSON.stringify(current.parameters, null, 2)}</pre></details>
      <label className="settings-field"><span>{t('toolArguments')}</span><textarea rows={6} value={argumentsText} onChange={(event) => setArgumentsText(event.currentTarget.value)} /></label>
      {!session ? <p>{t('toolSelectSession')}</p> : !allowed ? <p>{t('toolNotAllowed')}</p> : <p>{t('toolSession', { name: session.title || session.effective.persona_name })}</p>}
      <button className="secondary-button" type="button" disabled={!allowed || active || sending} onClick={() => void call()}>{t(sending ? 'toolCalling' : 'callTool')}</button>
    </div> : null}
    {latest ? <div className="tool-output"><h3>{t('toolResult')}</h3><RunPanel run={latest} />{output.map((message) => <MessageParts key={message.message_id} parts={message.parts} />)}</div> : null}
    <h3>{t('searxng')}</h3>
    <p className="settings-note">{t('searxngHelp')}</p>
    {settings ? <>
      <label className="settings-field"><span>{t('searxngUrl')}</span><input type="url" value={settings.searxng_base_url || ''} onChange={(event) => setSettings({ ...settings, searxng_base_url: event.currentTarget.value || null })} /></label>
      <button className="primary-button" type="button" disabled={saving} onClick={() => void saveSettings()}>{t('save')}</button>
    </> : null}
    {feedback ? <p className="settings-feedback" role="status">{feedback}</p> : null}
    {error ? <p className="settings-error" role="alert">{error}</p> : null}
  </Panel>;
}

function exampleArguments(tool: HarnessTool): string {
  const properties = (tool.parameters.properties || {}) as Record<string, { type?: string; minimum?: number }>;
  const required = (tool.parameters.required || []) as string[];
  return JSON.stringify(Object.fromEntries(required.map((key) => {
    const schema = properties[key] || {};
    const value = schema.type === 'array' ? [] : schema.type === 'object' ? {} : schema.type === 'boolean' ? false : ['number', 'integer'].includes(schema.type || '') ? schema.minimum ?? 0 : '';
    return [key, value];
  })), null, 2);
}
