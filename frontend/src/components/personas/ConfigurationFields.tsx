import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectGroup,
  SelectItem,
} from '@/components/ui/select';
import { FieldGroup, Field, FieldLabel, FieldContent, FieldDescription } from '@/components/ui/field';
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
import { useId } from 'react';

import type { ContextPolicy, BoundedContextPolicy, Persona, SessionGenerationParameters } from '../../types/chat';
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

export function ContextFields({ value, onChange }: { value: ContextPolicy; onChange: (value: ContextPolicy) => void }) {
  const { t } = useTranslation('personas');
  const id = useId();
  const disabled = !value.history_enabled;
  const messageLimit = value.message_window.max_messages;
  const invalidMessageLimit = !Number.isInteger(messageLimit) || messageLimit < 1 || messageLimit > 10000;
  const patch = (change: Partial<ContextPolicy['compaction']>) => onChange({ ...value, compaction: { ...value.compaction, ...change } });
  return <FieldGroup>
    <Field orientation="horizontal">
      <Switch id={id + '-history'} checked={value.history_enabled} onCheckedChange={(history_enabled) => onChange({ ...value, history_enabled })} />
      <FieldLabel htmlFor={id + '-history'}>{t('historyEnabled')}</FieldLabel>
    </Field>
    <Field data-disabled={disabled}>
      <FieldLabel id={id + '-strategy-label'}>{t('historyStrategy')}</FieldLabel>
      <ToggleGroup variant="segmented" value={[value.strategy]} disabled={disabled} aria-labelledby={id + '-strategy-label'}
        onValueChange={(next) => { if (next[0]) onChange({ ...value, strategy: next[0] as ContextPolicy['strategy'] }); }}>
        <ToggleGroupItem value="token_budget">{t('tokenBudget')}</ToggleGroupItem>
        <ToggleGroupItem value="message_window">{t('messageWindow')}</ToggleGroupItem>
      </ToggleGroup>
    </Field>
    {value.strategy === 'message_window' ? <Field data-invalid={invalidMessageLimit || undefined} data-disabled={disabled}>
      <FieldLabel htmlFor={id + '-message-limit'}>{t('maxMessages')}</FieldLabel>
      <Input id={id + '-message-limit'} type="number" required min={1} max={10000} step={1} disabled={disabled}
        aria-invalid={invalidMessageLimit} value={Number.isNaN(messageLimit) ? '' : messageLimit}
        onChange={(event) => onChange({ ...value, message_window: { max_messages: event.currentTarget.value === '' ? NaN : Number(event.currentTarget.value) } })} />
    </Field> : <>
    <Field orientation="horizontal" data-disabled={disabled}>
      <Switch id={id + '-compaction'} disabled={disabled} checked={value.compaction.enabled} onCheckedChange={(enabled) => patch({ enabled })} />
      <FieldLabel htmlFor={id + '-compaction'}>{t('autoCompaction')}</FieldLabel>
    </Field>
    <Collapsible>
      <CollapsibleTrigger render={<Button variant="ghost" size="sm" />} disabled={disabled}>{t('compactionAdvanced')}</CollapsibleTrigger>
      <CollapsibleContent>
        <FieldGroup className="grid gap-4 sm:grid-cols-2">
          {(['trigger_percent', 'target_percent'] as const).map((key) => {
            const number = value.compaction[key];
            const invalid = !Number.isInteger(number) || number <= 0 || number >= 100
              || value.compaction.target_percent >= value.compaction.trigger_percent;
            return <Field key={key} data-invalid={invalid || undefined} data-disabled={disabled}>
              <FieldLabel htmlFor={id + key}>{t(key === 'trigger_percent' ? 'compactionTrigger' : 'compactionTarget')}</FieldLabel>
              <Input id={id + key} type="number" required min={key === 'trigger_percent' ? value.compaction.target_percent + 1 : 1}
                max={key === 'target_percent' ? value.compaction.trigger_percent - 1 : 99} step={1} disabled={disabled}
                aria-invalid={invalid} value={Number.isNaN(number) ? '' : number}
                onChange={(event) => patch({ [key]: event.currentTarget.value === '' ? NaN : Number(event.currentTarget.value) })} />
            </Field>;
          })}
          <Field data-disabled={disabled}>
            <FieldLabel htmlFor={id + '-summary'}>{t('compactionSummaryTokens')}</FieldLabel>
            <Input id={id + '-summary'} type="number" min={1} step={1} disabled={disabled} placeholder={t('compactionAutomatic')}
              value={value.compaction.max_summary_tokens ?? ''}
              onChange={(event) => patch({ max_summary_tokens: event.currentTarget.value === '' ? null : Number(event.currentTarget.value) })} />
          </Field>
        </FieldGroup>
      </CollapsibleContent>
    </Collapsible>
    </>}
    <Field orientation="horizontal">
      <Switch id={id + '-attachments'} checked={value.include_attachments === 'explicit'}
        onCheckedChange={(enabled) => onChange({ ...value, include_attachments: enabled ? 'explicit' : 'none' })} />
      <FieldLabel htmlFor={id + '-attachments'}>{t('includeAttachments')}</FieldLabel>
    </Field>
  </FieldGroup>;
}

export function BoundedContextFields({
  value,
  onChange,
  showAttachments = true,
  showDescriptions = true,
  className,
}: {
  value: BoundedContextPolicy;
  showAttachments?: boolean;
  showDescriptions?: boolean;
  className?: string;
  onChange: (value: BoundedContextPolicy) => void;
}) {
  const { t } = useTranslation('personas');
  return (
    <>
      <FieldGroup className={className ?? 'grid gap-4 sm:grid-cols-2'}>
        <Field>
          <FieldLabel>{t('maxMessages')}</FieldLabel>
          <Input
            type="number"
            min={0}
            max={10000}
            placeholder={t('unlimited')}
            step={1}
            value={Number.isNaN(value.max_messages) ? '' : (value.max_messages ?? '')}
            onChange={(event) =>
              onChange({
                ...value,
                max_messages: event.currentTarget.value === '' ? null : Number(event.currentTarget.value),
              })
            }
          />
          {showDescriptions ? <FieldDescription>{t('maxMessagesDescription')}</FieldDescription> : null}
        </Field>
        <Field>
          <FieldLabel>{t('maxChars')}</FieldLabel>
          <Input
            type="number"
            min={1}
            max={1000000}
            placeholder={t('unlimited')}
            step={1}
            value={Number.isNaN(value.max_chars) ? '' : (value.max_chars ?? '')}
            onChange={(event) =>
              onChange({
                ...value,
                max_chars: event.currentTarget.value === '' ? null : Number(event.currentTarget.value),
              })
            }
          />
          {showDescriptions ? <FieldDescription>{t('maxCharsDescription')}</FieldDescription> : null}
        </Field>
      </FieldGroup>
      {showAttachments ? <Field orientation="horizontal">
        <Switch
          checked={value.include_attachments === 'explicit'}
          onCheckedChange={(enabled) =>
            onChange({ ...value, include_attachments: enabled ? 'explicit' : 'none' })
          }
        />
        <FieldLabel>{t('includeAttachments')}</FieldLabel>
      </Field> : null}
    </>
  );
}

export function GenerationFields({
  value,
  onChange,
}: {
  value: SessionGenerationParameters;
  onChange: (value: SessionGenerationParameters) => void;
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
        onChange={(event) => onChange({ temperature: event.currentTarget.value === '' ? null : Number(event.currentTarget.value) })}
      />
    </Field>
  );
}

export function ToolsField({
  tools,
  value,
  onChange,
  allowed,
}: {
  tools: HarnessTool[];
  value: string[];
  onChange: (values: string[]) => void;
  allowed?: string[];
}) {
  const { t } = useTranslation('settings');
  const { t: p } = useTranslation('personas');
  return (
    <FieldGroup className="context-binding-list gap-3" role="group" aria-label={p('tools')}>
      {!tools.length ? <p className="model-empty">{p('noTools')}</p> : null}
      {tools.map((tool) => (
        <Field orientation="horizontal" className="context-binding-row" key={tool.name}>
          <Checkbox
            checked={value.includes(tool.name) && (!allowed || allowed.includes(tool.name))}
            disabled={!!allowed && !allowed.includes(tool.name)}
            onCheckedChange={(enabled) =>
              onChange(
                enabled
                  ? tools
                      .filter((item) => (!allowed || allowed.includes(item.name)) && (item.name === tool.name || value.includes(item.name)))
                      .map((item) => item.name)
                  : value.filter((name) => name !== tool.name && (!allowed || allowed.includes(name))),
              )
            }
          />
          <FieldContent>
            <FieldLabel>{tool.name}</FieldLabel>
            <FieldDescription className="flex flex-wrap items-center gap-2">
              {allowed && !allowed.includes(tool.name) ? <span>{p('projectToolDisabled')}</span> : null}
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
  items,
  ids,
  onChange,
  disabled = false,
}: {
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
    <div className="context-binding-list">
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
    </div>
  );
}
