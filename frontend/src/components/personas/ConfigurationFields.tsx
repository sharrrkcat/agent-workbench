import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectGroup,
  SelectItem,
} from '@/components/ui/select';
import { FieldGroup, Field, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Checkbox } from '@/components/ui/checkbox';
import { Avatar, AvatarImage, AvatarFallback } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { ArrowDown, ArrowUp, ShieldCheck, UserRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { ContextPolicy, SessionGenerationParameters } from '../../types/chat';
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

type ModelSelectProps = { profiles: ModelProfile[]; value: string | null; onChange: (id: string) => void };

export function ModelSelect({
  profiles,
  value,
  onChange,
  disabled,
  className,
}: ModelSelectProps & { disabled?: boolean; className?: string }) {
  const { t } = useTranslation('personas');
  const options = profiles.filter((p) => p.kind === 'llm');
  const selected = options.find((p) => p.id === value);
  const available = options.some((p) => p.enabled);
  const emptyLabel = t(available ? 'selectModel' : 'noModels');
  return (
    <Select
      value={value || ''}
      disabled={disabled || !available}
      onValueChange={(selected) => onChange(selected ?? '')}
      items={[
        ...(!value ? [{ value: '', label: emptyLabel }] : []),
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
        aria-label={t('model')}
        title={selected?.name || (value ? t('unavailable') : emptyLabel)}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {!value ? (
            <SelectItem value="" disabled>
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

export function ContextFields({
  value,
  onChange,
}: {
  value: ContextPolicy;
  onChange: (value: ContextPolicy) => void;
}) {
  const { t } = useTranslation('personas');
  return (
    <>
      <FieldGroup className="grid gap-4 sm:grid-cols-2">
        <Field>
          <FieldLabel>{t('history')}</FieldLabel>
          <Select
            value={value.mode}
            onValueChange={(selected) =>
              onChange({ ...value, mode: (selected ?? '') as ContextPolicy['mode'] })
            }
            items={(
              ['session', 'recent_messages', 'current_message', 'selected_message', 'none'] as const
            ).map((mode) => ({ value: mode, label: t('contextModes.' + mode) }))}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(['session', 'recent_messages', 'current_message', 'selected_message', 'none'] as const).map(
                (mode) => (
                  <SelectItem key={mode} value={mode}>
                    {t('contextModes.' + mode)}
                  </SelectItem>
                ),
              )}
            </SelectContent>
          </Select>
        </Field>
        <Field>
          <FieldLabel>{t('maxMessages')}</FieldLabel>
          <Input
            type="number"
            min={1}
            max={10000}
            placeholder={value.mode === 'recent_messages' ? '20' : t('unlimited')}
            step={1}
            value={Number.isNaN(value.max_messages) ? '' : (value.max_messages ?? '')}
            onChange={(event) =>
              onChange({
                ...value,
                max_messages: event.currentTarget.value === '' ? null : Number(event.currentTarget.value),
              })
            }
          />
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
        </Field>
      </FieldGroup>
      <Field orientation="horizontal">
        <Switch
          checked={value.include_attachments === 'explicit'}
          onCheckedChange={(enabled) =>
            onChange({ ...value, include_attachments: enabled ? 'explicit' : 'none' })
          }
        />
        <FieldLabel>{t('includeAttachments')}</FieldLabel>
      </Field>
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
  return (
    <Field>
      <FieldLabel htmlFor="session-temperature">{t('params.temperature')}</FieldLabel>
      <Input
        id="session-temperature"
        type="number"
        min={0}
        max={2}
        step={0.1}
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
}: {
  tools: HarnessTool[];
  value: string[];
  onChange: (values: string[]) => void;
}) {
  const { t } = useTranslation('settings');
  const { t: p } = useTranslation('personas');
  return (
    <div className="context-binding-list" role="group" aria-label={p('tools')}>
      {!tools.length ? <p className="model-empty">{p('noTools')}</p> : null}
      {tools.map((tool) => (
        <div className="context-binding-row" key={tool.name}>
          <Field orientation="horizontal">
            <Checkbox
              checked={value.includes(tool.name)}
              onCheckedChange={(enabled) =>
                onChange(
                  enabled
                    ? tools
                        .filter((item) => item.name === tool.name || value.includes(item.name))
                        .map((item) => item.name)
                    : value.filter((name) => name !== tool.name),
                )
              }
            />
            <FieldLabel>{tool.name}</FieldLabel>
          </Field>
          <span className="tool-permission-detail">
            <span>{t('toolRisk.' + tool.risk)}</span>
            {tool.requires_approval ? (
              <Tooltip>
                <TooltipTrigger render={<span tabIndex={0} aria-label={t('approvalRequired')} />}>
                  <ShieldCheck size={15} />
                </TooltipTrigger>
                <TooltipContent>{t('approvalRequired')}</TooltipContent>
              </Tooltip>
            ) : null}
          </span>
        </div>
      ))}
    </div>
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
