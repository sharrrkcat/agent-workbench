import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectGroup,
  SelectItem,
} from '@/components/ui/select';
import { FieldGroup, Field, FieldLabel, FieldContent, FieldDescription, FieldSet, FieldLegend } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Checkbox } from '@/components/ui/checkbox';
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { ArrowDown, ArrowUp, ShieldCheck, UserRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useId, type ReactNode } from 'react';

import type { ContextPolicy, Persona, SessionGenerationParameters } from '../../types/chat';
import type { ModelProfile } from '../../types/models';
import type { HarnessTool } from '../../types/tools';
import { API_BASE_URL } from '../../api/url';
import { resolveAttachmentUrlFromBase } from '../../api/url';

export function PersonaAvatar({ name, attachmentId }: { name: string; attachmentId: string | null }) {
  return (
    <Avatar className="persona-avatar">
      {attachmentId ? (
        <AvatarImage
          src={resolveAttachmentUrlFromBase(API_BASE_URL, `local://attachments/${attachmentId}`)}
          alt={name}
        />
      ) : null}
      <AvatarFallback><UserRound aria-hidden="true" /></AvatarFallback>
    </Avatar>
  );
}

type ModelSelectProps = { profiles: ModelProfile[]; value: string | null; onChange: (id: string) => void; inheritLabel?: string; label?: string; kind?: ModelProfile['kind'] };

export function ModelSelect({
  profiles,
  value,
  onChange,
  disabled,
  className,
  inheritLabel,
  label,
  kind = 'llm',
}: ModelSelectProps & { disabled?: boolean; className?: string }) {
  const { t } = useTranslation('personas');
  const options = profiles.filter((p) => p.kind === kind);
  const selected = options.find((p) => p.id === value);
  const available = options.some((p) => p.enabled);
  const emptyLabel = inheritLabel || t(available ? 'selectModel' : 'noModels');
  return (
    <Select
      value={value || ''}
      disabled={disabled || (!available && !inheritLabel)}
      onValueChange={(selected) => onChange(selected ?? '')}
      items={[
        ...(!value || inheritLabel ? [{ value: '', label: emptyLabel }] : []),
        ...options.map((p) => ({
          value: p.id,
          label: (
            <>
              {p.name}
              {p.enabled ? '' : ` (${t('disabled')})`}
            </>
          ),
        })),
        ...(value && !selected ? [{ value: value, label: t('unavailable') }] : []),
      ]}
    >
      <SelectTrigger
        className={className}
        aria-label={label || t('model')}
        title={selected?.name || (value ? t('unavailable') : emptyLabel)}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {!value || inheritLabel ? (
            <SelectItem value="" disabled={!inheritLabel}>
              {emptyLabel}
            </SelectItem>
          ) : null}
          {options.map((p) => (
            <SelectItem key={p.id} value={p.id} disabled={!p.enabled}>
              {p.name}
              {p.enabled ? '' : ` (${t('disabled')})`}
            </SelectItem>
          ))}
          {value && !selected ? (
            <SelectItem value={value} disabled>
              {t('unavailable')}
            </SelectItem>
          ) : null}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}

export function ModelField(props: ModelSelectProps) {
  const { t } = useTranslation('personas');
  return (
    <Field>
      <FieldLabel>{t('model')}</FieldLabel>
      <ModelSelect {...props} />
    </Field>
  );
}

export function PersonaField({ label, personas, value, onChange, invalid = false }: {
  label: string; personas: Persona[]; value: string; onChange: (id: string) => void; invalid?: boolean;
}) {
  const id = useId();
  const { t } = useTranslation('personas');
  return (
    <Field data-invalid={invalid || undefined}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Select value={value} onValueChange={(next) => { if (next) onChange(next); }}
        items={[{ value: '', label: t('selectPersona') }, ...personas.map((p) => ({ value: p.id, label: p.name }))]}>
        <SelectTrigger id={id} aria-invalid={invalid}><SelectValue /></SelectTrigger>
        <SelectContent><SelectGroup>
          <SelectItem value="" disabled>{t('selectPersona')}</SelectItem>
          {personas.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}
        </SelectGroup></SelectContent>
      </Select>
    </Field>
  );
}

export function ContextFields({ value, onChange, showAttachments = true, harnessEnabled = false, className, advancedAction, onMessageLimitCommit }: {
  value: ContextPolicy; onChange: (value: ContextPolicy) => void; showAttachments?: boolean; harnessEnabled?: boolean; className?: string;
  advancedAction?: ReactNode; onMessageLimitCommit?: () => void;
}) {
  const { t } = useTranslation('personas');
  const id = useId();
  const disabled = !value.history_enabled;
  const messageLimit = value.message_window.max_messages;
  const invalidMessageLimit = !Number.isInteger(messageLimit) || messageLimit < 1 || messageLimit > 10000;
  const retrieval = value.strategy === 'history_retrieval';
  return <FieldGroup className={className}>
    <Field orientation="horizontal">
      <Switch id={id + '-history'} checked={value.history_enabled} onCheckedChange={(history_enabled) => onChange({ ...value, history_enabled })} />
      <FieldLabel htmlFor={id + '-history'}>{t('historyEnabled')}</FieldLabel>
    </Field>
    <Field>
      <div className="flex items-center gap-1">
        <FieldLabel id={id + '-strategy-label'}>{t('historyStrategy')}</FieldLabel>
        {retrieval ? advancedAction : null}
      </div>
      <ToggleGroup variant="segmented" className="flex-wrap" value={[value.strategy]} aria-labelledby={id + '-strategy-label'}
        onValueChange={(next) => { if (next[0]) onChange({ ...value, strategy: next[0] as ContextPolicy['strategy'] }); }}>
        <ToggleGroupItem value="token_budget">{t('tokenBudget')}</ToggleGroupItem>
        <ToggleGroupItem value="message_window">{t('messageWindow')}</ToggleGroupItem>
        <ToggleGroupItem value="history_retrieval" disabled={!harnessEnabled}>{t('historyRetrieval')}</ToggleGroupItem>
      </ToggleGroup>
      {!harnessEnabled ? <FieldDescription>{t('retrievalHarnessRequired')}</FieldDescription> : null}
    </Field>
    {value.strategy === 'message_window' ? <Field data-invalid={invalidMessageLimit || undefined} data-disabled={disabled}>
      <FieldLabel htmlFor={id + '-message-limit'}>{t('maxMessages')}</FieldLabel>
      <Input id={id + '-message-limit'} type="number" required min={1} max={10000} step={1} disabled={disabled}
        aria-invalid={invalidMessageLimit} value={Number.isNaN(messageLimit) ? '' : messageLimit}
        onBlur={onMessageLimitCommit ? (event) => { if (event.currentTarget.validity.valid) onMessageLimitCommit(); } : undefined}
        onKeyDown={onMessageLimitCommit ? (event) => { if (event.key === 'Enter') { event.preventDefault(); if (event.currentTarget.reportValidity()) event.currentTarget.blur(); } } : undefined}
        onChange={(event) => onChange({ ...value, message_window: { max_messages: event.currentTarget.value === '' ? NaN : Number(event.currentTarget.value) } })} />
    </Field> : <>
    {!retrieval ? <Field orientation="horizontal" className={advancedAction ? '[&>[data-slot=field-label]]:flex-none' : undefined}>
      <Switch id={id + '-compaction'} checked={value.compaction.enabled} onCheckedChange={(enabled) => onChange({ ...value, compaction: { ...value.compaction, enabled } })} />
      <FieldLabel htmlFor={id + '-compaction'}>{t('autoCompaction')}</FieldLabel>
      {advancedAction}
    </Field> : null}
    {!advancedAction ? <Collapsible>
      <CollapsibleTrigger render={<Button variant="ghost" size="sm" />}>{t('compactionAdvanced')}</CollapsibleTrigger>
      <CollapsibleContent><ContextAdvancedFields value={value} onChange={onChange} /></CollapsibleContent>
    </Collapsible> : null}
    </>}
    {showAttachments ? <Field orientation="horizontal">
      <Switch id={id + '-attachments'} checked={value.include_attachments === 'explicit'}
        onCheckedChange={(enabled) => onChange({ ...value, include_attachments: enabled ? 'explicit' : 'none' })} />
      <FieldLabel htmlFor={id + '-attachments'}>{t('includeAttachments')}</FieldLabel>
    </Field> : null}
  </FieldGroup>;
}

export function ContextAdvancedFields({ value, onChange }: { value: ContextPolicy; onChange: (value: ContextPolicy) => void }) {
  const { t } = useTranslation('personas');
  const id = useId();
  const retrieval = value.strategy === 'history_retrieval';
  const budget = retrieval ? value.retrieval : value.compaction;
  const patch = (change: Partial<ContextPolicy['compaction'] & ContextPolicy['retrieval']>) =>
    onChange(retrieval ? { ...value, retrieval: { ...value.retrieval, ...change } } : { ...value, compaction: { ...value.compaction, ...change } });
  return <FieldGroup className="grid gap-4 sm:grid-cols-2">
    {(['trigger_percent', 'target_percent'] as const).map((key) => {
      const number = budget[key];
      const invalid = !Number.isInteger(number) || number <= 0 || number >= 100
        || budget.target_percent >= budget.trigger_percent;
      return <Field key={key} data-invalid={invalid || undefined}>
        <FieldLabel htmlFor={id + key}>{t(key === 'trigger_percent' ? (retrieval ? 'retrievalTrigger' : 'compactionTrigger') : (retrieval ? 'retrievalTarget' : 'compactionTarget'))}</FieldLabel>
        <Input id={id + key} type="number" required min={key === 'trigger_percent' ? budget.target_percent + 1 : 1}
          max={key === 'target_percent' ? budget.trigger_percent - 1 : 99} step={1}
          aria-invalid={invalid} value={Number.isNaN(number) ? '' : number}
          onChange={(event) => patch({ [key]: event.currentTarget.value === '' ? NaN : Number(event.currentTarget.value) })} />
      </Field>;
    })}
    <Field>
      <FieldLabel htmlFor={id + '-summary'}>{t(retrieval ? 'checkpointTokens' : 'compactionSummaryTokens')}</FieldLabel>
      <Input id={id + '-summary'} type="number" min={1} step={1} placeholder={t('compactionAutomatic')}
        value={(retrieval ? value.retrieval.max_checkpoint_tokens : value.compaction.max_summary_tokens) ?? ''}
        onChange={(event) => patch({ [retrieval ? 'max_checkpoint_tokens' : 'max_summary_tokens']: event.currentTarget.value === '' ? null : Number(event.currentTarget.value) })} />
    </Field>
  </FieldGroup>;
}

export function GenerationFields({
  value,
  onChange,
  onCommit,
}: {
  value: SessionGenerationParameters;
  onChange: (value: SessionGenerationParameters) => void;
  onCommit?: () => void;
}) {
  const { t } = useTranslation('llm');
  const { t: p } = useTranslation('personas');
  const id = useId();
  return (
    <Field>
      <FieldLabel htmlFor={id}>{t('params.temperature')}</FieldLabel>
      <Input
        id={id}
        type="number"
        min={0}
        max={2}
        step="any"
        placeholder={p('modelDefault')}
        value={value.temperature ?? ''}
        onBlur={onCommit ? (event) => { if (event.currentTarget.validity.valid) onCommit(); } : undefined}
        onKeyDown={onCommit ? (event) => { if (event.key === 'Enter') { event.preventDefault(); if (event.currentTarget.reportValidity()) event.currentTarget.blur(); } } : undefined}
        onChange={(event) => onChange({ temperature: event.currentTarget.value === '' ? null : Number(event.currentTarget.value) })}
      />
    </Field>
  );
}

export function ToolsField({
  tools,
  value,
  onChange,
}: {
  tools: HarnessTool[];
  value: string[];
  onChange: (values: string[]) => void;
}) {
  const { t } = useTranslation('settings');
  const { t: p } = useTranslation('personas');
  const id = useId();
  const generalTools = tools.filter((tool) => tool.scope === 'general');
  return (
    <FieldGroup className="context-binding-list gap-3" role="group" aria-label={p('tools')}>
      {!generalTools.length ? <p className="model-empty">{p('noTools')}</p> : null}
      {generalTools.map((tool) => (
        <Field orientation="horizontal" className="context-binding-row" key={tool.name}>
          <Checkbox
            id={id + '-' + tool.name}
            checked={value.includes(tool.name)}
            onCheckedChange={(enabled) =>
              onChange(
                enabled
                  ? generalTools
                      .filter((item) => item.name === tool.name || value.includes(item.name))
                      .map((item) => item.name)
                  : value.filter((name) => name !== tool.name),
              )
            }
          />
          <FieldContent>
            <FieldLabel htmlFor={id + '-' + tool.name}>{tool.name}</FieldLabel>
            <FieldDescription className="flex flex-wrap items-center gap-2">
              <span>{t('toolRisk.' + tool.risk)}</span>
              {tool.requires_approval ? (
                <Tooltip>
                  <TooltipTrigger render={<span tabIndex={0} className="inline-flex" aria-label={t('approvalRequired')} />}>
                    <ShieldCheck size={15} />
                  </TooltipTrigger>
                  <TooltipContent>{t('approvalRequired')}</TooltipContent>
                </Tooltip>
              ) : null}
            </FieldDescription>
          </FieldContent>
        </Field>
      ))}
    </FieldGroup>
  );
}

export function BindingsField({
  label,
  items,
  ids,
  onChange,
  disabled = false,
}: {
  label?: string;
  items: Array<{ id: string; name: string; enabled: boolean }>;
  ids: string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation('personas');
  const sorted = [
    ...ids.map(
      (id) => items.find((item) => item.id === id) || { id, name: t('unavailable'), enabled: false },
    ),
    ...items.filter((item) => !ids.includes(item.id)),
  ];
  const move = (id: string, delta: number) => {
    const next = [...ids];
    const index = next.indexOf(id);
    [next[index], next[index + delta]] = [next[index + delta], next[index]];
    onChange(next);
  };
  return (
    <FieldSet className="context-binding-list">
      {label ? <FieldLegend>{label}</FieldLegend> : null}
      {!sorted.length ? <p className="model-empty">{t('noResources')}</p> : null}
      {sorted.map((item) => (
        <div className="context-binding-row" key={item.id}>
          <Field orientation="horizontal" disabled={disabled}>
            <Checkbox
              checked={ids.includes(item.id)}
              disabled={disabled}
              onCheckedChange={(checked) =>
                onChange(checked ? [...ids, item.id] : ids.filter((id) => id !== item.id))
              }
            />
            <FieldLabel>{`${item.name}${item.enabled ? '' : ` (${t('disabled')})`}`}</FieldLabel>
          </Field>
          {ids.includes(item.id) && !disabled ? (
            <div className="model-actions">
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={t('moveUp')}
                      disabled={ids.indexOf(item.id) === 0}
                      onClick={() => move(item.id, -1)}
                    />
                  }
                >
                  <ArrowUp size={14} />
                </TooltipTrigger>
                <TooltipContent>{t('moveUp')}</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      aria-label={t('moveDown')}
                      disabled={ids.indexOf(item.id) === ids.length - 1}
                      onClick={() => move(item.id, 1)}
                    />
                  }
                >
                  <ArrowDown size={14} />
                </TooltipTrigger>
                <TooltipContent>{t('moveDown')}</TooltipContent>
              </Tooltip>
            </div>
          ) : null}
        </div>
      ))}
    </FieldSet>
  );
}
