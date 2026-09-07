import { ArrowDown, ArrowUp, UserRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ReactNode } from 'react';
import type { ContextPolicy, GenerationParameters } from '../../types/chat';
import type { ModelProfile } from '../../types/models';
import { API_BASE_URL } from '../../api/url';
import { resolveAttachmentUrlFromBase } from '../../api/url';

export const defaultPolicy = (): ContextPolicy => ({ mode: 'session', max_messages: null, max_chars: null, include_system_prompt: true, include_attachments: 'explicit' });

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="settings-field"><span>{label}</span>{children}</label>;
}

export function IconButton({ label, children, disabled, onClick }: { label: string; children: ReactNode; disabled?: boolean; onClick: () => void }) {
  return <button type="button" className="icon-button" title={label} aria-label={label} disabled={disabled} onClick={onClick}>{children}</button>;
}

export function PersonaAvatar({ name, attachmentId }: { name: string; attachmentId: string | null }) {
  return <span className="persona-avatar">{attachmentId ? <img src={resolveAttachmentUrlFromBase(API_BASE_URL, `local://attachments/${attachmentId}`)} alt={name} /> : <UserRound size={19} aria-hidden="true" />}</span>;
}

export function ModelField({ profiles, value, onChange, inheritLabel }: { profiles: ModelProfile[]; value: string | null; onChange: (id: string | null) => void; inheritLabel: string }) {
  const { t } = useTranslation('personas');
  const options = profiles.filter((p) => p.kind === 'llm');
  return <Field label={t('model')}><select value={value || ''} onChange={(e) => onChange(e.target.value || null)}>
    <option value="">{inheritLabel}</option>
    {options.map((p) => <option key={p.id} value={p.id} disabled={!p.enabled}>{p.name}{p.enabled ? '' : ` (${t('disabled')})`}</option>)}
    {value && !options.some((p) => p.id === value) ? <option value={value} disabled>{t('unavailable')}</option> : null}
  </select></Field>;
}

export function ContextFields({ value, onChange }: { value: ContextPolicy; onChange: (value: ContextPolicy) => void }) {
  const { t } = useTranslation('personas');
  return <>
    <div className="model-form-grid">
      <Field label={t('history')}><select value={value.mode} onChange={(e) => onChange({ ...value, mode: e.target.value as ContextPolicy['mode'] })}>
        {(['session', 'recent_messages', 'current_message', 'selected_message', 'none'] as const).map((mode) => <option key={mode} value={mode}>{t('contextModes.' + mode)}</option>)}
      </select></Field>
      <NumberField label={t('maxMessages')} value={value.max_messages} min={1} max={10000} placeholder={value.mode === 'recent_messages' ? '20' : t('unlimited')} onChange={(max_messages) => onChange({ ...value, max_messages })} />
      <NumberField label={t('maxChars')} value={value.max_chars} min={1} max={1000000} placeholder={t('unlimited')} onChange={(max_chars) => onChange({ ...value, max_chars })} />
    </div>
    <Check label={t('includePrompt')} checked={value.include_system_prompt} onChange={(include_system_prompt) => onChange({ ...value, include_system_prompt })} />
    <Check label={t('includeAttachments')} checked={value.include_attachments === 'explicit'} onChange={(enabled) => onChange({ ...value, include_attachments: enabled ? 'explicit' : 'none' })} />
  </>;
}

export function GenerationFields({ value, onChange }: { value: GenerationParameters; onChange: (value: GenerationParameters) => void }) {
  const { t } = useTranslation('llm');
  const { t: p } = useTranslation('personas');
  const fields: Array<[keyof Omit<GenerationParameters, 'stop'>, number | undefined, number | undefined, number]> = [
    ['temperature', 0, 2, 0.1], ['top_p', 0, 1, 0.05], ['max_tokens', 1, undefined, 1],
    ['presence_penalty', -2, 2, 0.1], ['frequency_penalty', -2, 2, 0.1], ['seed', undefined, undefined, 1],
  ];
  const stopValue = Array.isArray(value.stop) ? value.stop.join('\n') : value.stop || '';
  return <div className="model-form-grid">
    {fields.map(([key, min, max, step]) => <NumberField key={key} label={t('params.' + key)} value={value[key]} min={min} max={max} step={step} placeholder={p('modelDefault')} onChange={(v) => onChange({ ...value, [key]: v })} />)}
    <Field label={t('params.stop')}><textarea rows={2} value={stopValue} onChange={(e) => { const values = e.target.value.split('\n'); onChange({ ...value, stop: e.target.value ? values.length > 1 ? values : values[0] : null }); }} /></Field>
  </div>;
}

export function ToolsField({ value, onChange }: { value: string[]; onChange: (values: string[]) => void }) {
  const { t } = useTranslation('personas');
  return <Field label={t('tools')}><textarea rows={3} value={value.join('\n')} onChange={(e) => onChange(e.target.value ? e.target.value.split('\n') : [])} /></Field>;
}

export function Check({ label, checked, disabled, onChange }: { label: string; checked: boolean; disabled?: boolean; onChange: (value: boolean) => void }) {
  return <label className="settings-toggle"><input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} /><span>{label}</span></label>;
}

export function NumberField({ label, value, min, max, step = 1, placeholder, onChange }: { label: string; value?: number | null; min?: number; max?: number; step?: number; placeholder?: string; onChange: (value: number | null) => void }) {
  return <Field label={label}><input type="number" value={value ?? ''} min={min} max={max} step={step} placeholder={placeholder} onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} /></Field>;
}

export function BindingsField({ items, ids, onChange, disabled = false }: { items: Array<{ id: string; name: string; enabled: boolean }>; ids: string[]; onChange: (ids: string[]) => void; disabled?: boolean }) {
  const { t } = useTranslation('personas');
  const sorted = [...ids.map((id) => items.find((item) => item.id === id) || { id, name: t('unavailable'), enabled: false }), ...items.filter((item) => !ids.includes(item.id))];
  const move = (id: string, delta: number) => {
    const next = [...ids]; const index = next.indexOf(id);
    [next[index], next[index + delta]] = [next[index + delta], next[index]];
    onChange(next);
  };
  return <div className="context-binding-list">
    {!sorted.length ? <p className="model-empty">{t('noResources')}</p> : null}
    {sorted.map((item) => <div className="context-binding-row" key={item.id}>
      <Check label={`${item.name}${item.enabled ? '' : ` (${t('disabled')})`}`} checked={ids.includes(item.id)} disabled={disabled} onChange={(checked) => onChange(checked ? [...ids, item.id] : ids.filter((id) => id !== item.id))} />
      {ids.includes(item.id) && !disabled ? <div className="model-actions">
        <IconButton label={t('moveUp')} disabled={ids.indexOf(item.id) === 0} onClick={() => move(item.id, -1)}><ArrowUp size={14} /></IconButton>
        <IconButton label={t('moveDown')} disabled={ids.indexOf(item.id) === ids.length - 1} onClick={() => move(item.id, 1)}><ArrowDown size={14} /></IconButton>
      </div> : null}
    </div>)}
  </div>;
}
