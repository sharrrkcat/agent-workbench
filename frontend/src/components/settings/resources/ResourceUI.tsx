import { Children, cloneElement, createContext, isValidElement, useCallback, useContext, useEffect, useId, useRef, useState } from 'react';
import type { ReactElement, ReactNode } from 'react';
import { LoaderCircle, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/http';

export const SettingsLeaveContext = createContext<(guard: () => boolean) => () => void>(() => () => undefined);

export function useResourceGuard(dirty: boolean, busy: boolean) {
  const { t } = useTranslation('settings');
  const register = useContext(SettingsLeaveContext);
  const guard = useCallback(() => !busy && (!dirty || window.confirm(t('resources.discardConfirm'))), [busy, dirty, t]);
  useEffect(() => register(guard), [guard, register]);
  useEffect(() => {
    if (!dirty && !busy) return;
    const beforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, [dirty, busy]);
  return guard;
}

export function errorText(error: unknown) {
  return error instanceof ApiError ? `${error.code}: ${error.message}` : String(error);
}

export function useResourceTask() {
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const lock = useRef(false);
  const live = useRef(true);
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  async function run<T>(key: string, action: () => Promise<T>, message = ''): Promise<T | undefined> {
    if (lock.current) return;
    lock.current = true; setBusy(key); setError(''); setNotice('');
    try {
      const result = await action();
      if (live.current) setNotice(message);
      return result;
    } catch (reason) {
      if (live.current) setError(errorText(reason));
    } finally {
      lock.current = false;
      if (live.current) setBusy('');
    }
  }
  return { busy, error, notice, setError, setNotice, run };
}

export function Feedback({ error, notice }: { error: string; notice?: string }) {
  return <div className="resource-feedback" role={error ? 'alert' : 'status'}>
    {error ? <span className="error-text">{error}</span> : <span className="success-text">{notice}</span>}
  </div>;
}

export function ResourceIcon({ label, children, onClick, disabled, busy = false, danger = false }: {
  label: string; children: ReactNode; onClick: () => void; disabled?: boolean; busy?: boolean; danger?: boolean;
}) {
  return <button type="button" className={`icon-button resource-icon${danger ? ' danger' : ''}`} title={label} aria-label={label}
    disabled={disabled || busy} onClick={onClick}>{busy ? <LoaderCircle size={16} className="spin" /> : children}</button>;
}

export function ResourceTabs<T extends string>({ value, onChange, tabs, disabled = false }: {
  value: T; onChange: (value: T) => void; tabs: Array<{ id: T; label: string; disabled?: boolean }>; disabled?: boolean;
}) {
  const { t } = useTranslation('settings');
  return <div className="model-tabs resource-tabs" role="tablist" aria-label={t('resources.sections')}>
    {tabs.map((tab) => <button key={tab.id} type="button" role="tab" aria-selected={tab.id === value}
      disabled={disabled || tab.disabled} onClick={() => onChange(tab.id)}>{tab.label}</button>)}
  </div>;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  const id = useId();
  return <div className="settings-field resource-field"><label htmlFor={id}>{label}</label>
    {Children.map(children, (child) => isValidElement(child) && ['input', 'select', 'textarea'].includes(String(child.type))
      ? cloneElement(child as ReactElement<{ id: string }>, { id }) : child)}
  </div>;
}

export function NumberInput({ label, value, onChange, min, max, step = 1, optional = false }: {
  label: string; value: number | null; onChange: (value: number | null) => void; min: number; max: number;
  step?: number; optional?: boolean;
}) {
  const [text, setText] = useState(value == null || Number.isNaN(value) ? '' : String(value));
  useEffect(() => setText(value == null || Number.isNaN(value) ? '' : String(value)), [value]);
  return <Field label={label}><input type="number" min={min} max={max} step={step} required={!optional}
    value={text} onChange={(event) => {
      const raw = event.target.value; setText(raw);
      onChange(raw === '' ? optional ? null : Number.NaN : Number(raw));
    }} /></Field>;
}

export function ResourceLoading({ error, retry }: { error?: string; retry?: () => void }) {
  const { t } = useTranslation('settings');
  return <div className="resource-loading" role={error ? 'alert' : 'status'}>
    {error || t('common:loading')}
    {error && retry ? <ResourceIcon label={t('resources.refresh')} onClick={retry}><RefreshCw size={16} /></ResourceIcon> : null}
  </div>;
}

export function equalDraft(left: unknown, right: unknown) { return JSON.stringify(left) === JSON.stringify(right); }

export function revealInvalidField(event: { target: EventTarget }) {
  if (!(event.target instanceof HTMLElement)) return;
  let details = event.target.closest('details');
  while (details) { details.open = true; details = details.parentElement?.closest('details') ?? null; }
}
