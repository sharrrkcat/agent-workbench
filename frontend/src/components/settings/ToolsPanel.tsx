import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Feedback } from './resources/ResourceUI';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';
import { Textarea } from '@/components/ui/textarea';
import { FieldGroup, Field, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toolsApi } from '../../api/tools';
import { useWorkbenchStore } from '../../store/useWorkbenchStore';
import type { HarnessSettings, HarnessTool } from '../../types/tools';
import { MessageParts } from '../messages/MessageParts';
import { RunPanel } from '../RunPanel';

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
    void Promise.all([toolsApi.listTools(), toolsApi.getToolSettings()])
      .then(([catalog, value]) => {
        if (!disposed) {
          setTools(catalog);
          setSettings(value);
        }
      })
      .catch((error: unknown) => {
        if (!disposed) setFeedback(error instanceof Error ? error.message : t('failed'));
      });
    return () => {
      disposed = true;
    };
  }, [t]);
  useEffect(() => {
    setFeedback('');
  }, [session?.session_id]);
  const current = tools.find((item) => item.name === selected);
  const allowed =
    !!current && !!session?.effective.tools_allowed.includes(current.name) && current.direct_callable;
  const active = runs.some(
    (run) =>
      run.session_id === session?.session_id &&
      ['PENDING', 'RUNNING', 'CANCELLING', 'WAITING_FOR_USER'].includes(run.status),
  );
  const latest = [...runs]
    .reverse()
    .find(
      (run) =>
        run.session_id === session?.session_id && run.kind === 'tool' && run.metadata?.tool_name === selected,
    );
  const output = latest ? messages.filter((message) => message.run_id === latest.run_id) : [];

  async function saveSettings() {
    if (!settings || saving) return;
    setSaving(true);
    try {
      const value = await toolsApi.updateToolSettings(settings);
      setSettings(value);
      setFeedback(t('saved'));
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : t('failed'));
    } finally {
      setSaving(false);
    }
  }

  async function call() {
    if (!session || !current || !allowed || active || sending) return;
    setFeedback('');
    try {
      const args: unknown = JSON.parse(argumentsText);
      if (!args || typeof args !== 'object' || Array.isArray(args)) throw new Error(t('toolArgumentsObject'));
      const result = await callTool(current.name, args as Record<string, unknown>);
      if (result && result.run.session_id === useWorkbenchStore.getState().currentSession?.session_id)
        setFeedback(t(result.run.status === 'WAITING_FOR_USER' ? 'approvalRequired' : 'toolCalled'));
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : t('failed'));
    }
  }

  return (
    <section className="settings-panel">
      <p className="settings-note">{t('toolDirectHelp')}</p>
      <div className="tools-layout">
        <div className="tool-catalog">
          <h2>{t('toolCatalog')}</h2>
          <ToggleGroup
            className="w-full"
            orientation="vertical"
            multiple={false}
            aria-label={t('toolCatalog')}
            value={[selected]}
            onValueChange={(values) => {
              const tool = tools.find((item) => item.name === values[0]);
              if (tool) {
                setSelected(tool.name);
                setArgumentsText(exampleArguments(tool));
                setFeedback('');
              }
            }}
          >
            {tools.map((tool) => (
              <ToggleGroupItem
                key={tool.name}
                value={tool.name}
                className="tool-selector h-auto min-h-14 w-full justify-start whitespace-normal py-2 text-left"
              >
                <span>
                  <span>{tool.name}</span>
                  <small>{t('toolDescriptions.' + tool.name)}</small>
                </span>
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </div>
        <div className="tool-workspace">
          {current ? (
            <div className="tool-call-form">
              <div className="resource-toolbar">
                <h2>{current.name}</h2>
                <div className="resource-meta">
                  <Badge variant="outline">{t('toolRisk.' + current.risk)}</Badge>
                  <Badge variant="secondary">
                    {t(current.requires_approval ? 'approvalRequired' : 'noApproval')}
                  </Badge>
                </div>
              </div>
              <Collapsible>
                <CollapsibleTrigger
                  render={<Button type="button" variant="ghost" className="justify-start" />}
                >
                  {t('toolSchema')}
                </CollapsibleTrigger>
                <CollapsibleContent keepMounted>
                  <pre className="part-json">{JSON.stringify(current.parameters, null, 2)}</pre>
                </CollapsibleContent>
              </Collapsible>
              <FieldGroup>
                <Field>
                  <FieldLabel>{t('toolArguments')}</FieldLabel>
                  <Textarea
                    className="min-h-32"
                    rows={6}
                    value={argumentsText}
                    onChange={(event) => setArgumentsText(event.currentTarget.value)}
                  />
                </Field>
              </FieldGroup>
              <p className="settings-note">
                {!session
                  ? t('toolSelectSession')
                  : !allowed
                    ? t('toolNotAllowed')
                    : t('toolSession', { name: session.title || session.effective.persona_name })}
              </p>
              <div className="resource-actions">
                <Button type="button" disabled={!allowed || active || sending} onClick={() => void call()}>
                  {t(sending ? 'toolCalling' : 'callTool')}
                </Button>
              </div>
            </div>
          ) : null}
          {latest ? (
            <div className="tool-output">
              <h3>{t('toolResult')}</h3>
              <RunPanel run={latest} />
              {output.map((message) => (
                <MessageParts key={message.message_id} parts={message.parts} />
              ))}
            </div>
          ) : null}
          <Feedback error={error || ''} notice={feedback} />
        </div>
      </div>
      <Separator />
      <section className="tool-search-settings" aria-label={t('searxng')}>
        <h2>{t('searxng')}</h2>
        <p className="settings-note">{t('searxngHelp')}</p>
        {settings ? (
          <FieldGroup>
            <Field>
              <FieldLabel>{t('searxngUrl')}</FieldLabel>
              <Input
                type="url"
                value={settings.searxng_base_url || ''}
                onChange={(event) =>
                  setSettings({ ...settings, searxng_base_url: event.currentTarget.value || null })
                }
              />
            </Field>
            <div className="settings-form-actions">
              <Button type="button" disabled={saving} onClick={() => void saveSettings()}>
                {t('save')}
              </Button>
            </div>
          </FieldGroup>
        ) : null}
      </section>
    </section>
  );
}

function exampleArguments(tool: HarnessTool): string {
  const properties = (tool.parameters.properties || {}) as Record<
    string,
    { type?: string; minimum?: number }
  >;
  const required = (tool.parameters.required || []) as string[];
  return JSON.stringify(
    Object.fromEntries(
      required.map((key) => {
        const schema = properties[key] || {};
        const value =
          schema.type === 'array'
            ? []
            : schema.type === 'object'
              ? {}
              : schema.type === 'boolean'
                ? false
                : ['number', 'integer'].includes(schema.type || '')
                  ? (schema.minimum ?? 0)
                  : '';
        return [key, value];
      }),
    ),
    null,
    2,
  );
}
