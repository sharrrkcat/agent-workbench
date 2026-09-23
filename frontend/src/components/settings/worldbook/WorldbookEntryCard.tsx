import { Badge } from '@/components/ui/badge';
import { CollapsibleTrigger, CollapsibleContent, Collapsible } from '@/components/ui/collapsible';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Switch } from '@/components/ui/switch';
import { Field, FieldLabel, FieldSet } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectGroup,
  SelectItem,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { ChevronDown, ChevronRight, GripVertical, LoaderCircle, RotateCcw, Save, Trash2 } from 'lucide-react';
import type { KeyboardEvent, PointerEvent } from 'react';
import { useTranslation } from 'react-i18next';
import type { WorldbookEntryInput } from '../../../types/worldbook';

export function WorldbookEntryCard({
  id,
  draft,
  expanded,
  dirty,
  busy,
  locked,
  dragging,
  error,
  onToggle,
  onUpdate,
  onEnabled,
  onSave,
  onReset,
  onDelete,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onPointerCancel,
  onKeyDown,
}: {
  id: string;
  draft: WorldbookEntryInput;
  expanded: boolean;
  dirty: boolean;
  busy: string;
  locked: boolean;
  dragging: boolean;
  error?: string;
  onToggle: () => void;
  onUpdate: (patch: Partial<WorldbookEntryInput>) => void;
  onEnabled: (enabled: boolean) => void;
  onSave: () => void;
  onReset: () => void;
  onDelete: () => void;
  onPointerDown?: (event: PointerEvent<HTMLButtonElement>) => void;
  onPointerMove?: (event: PointerEvent<HTMLButtonElement>) => void;
  onPointerUp?: (event: PointerEvent<HTMLButtonElement>) => void;
  onPointerCancel?: () => void;
  onKeyDown?: (event: KeyboardEvent<HTMLButtonElement>) => void;
}) {
  const { t } = useTranslation('worldbook');
  return (
    <Collapsible
      open={expanded}
      onOpenChange={onToggle}
      render={
        <article
          data-entry-id={id}
          className={`worldbook-entry-card${expanded ? ' expanded' : ''}${draft.enabled ? '' : ' disabled'}${dragging ? ' dragging' : ''}`}
        />
      }
    >
      <header className="worldbook-entry-card-header" onClick={onToggle}>
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                type="button"
                aria-label={t('dragNamed', { name: draft.name || t('newEntry') })}
                disabled={id === 'new' || locked}
                onClick={(event) => event.stopPropagation()}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={onPointerCancel}
                onKeyDown={onKeyDown}
                variant="ghost"
                size="icon"
                className="drag-handle touch-none"
              />
            }
          >
            <GripVertical data-icon="inline-start" />
          </TooltipTrigger>
          <TooltipContent>{t('dragToReorder')}</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger
            render={
              <CollapsibleTrigger
                render={
                  <Button
                    type="button"
                    aria-label={expanded ? t('collapse') : t('expand')}
                    variant="ghost"
                    size="icon"
                    onClick={(event) => event.stopPropagation()}
                  />
                }
              ></CollapsibleTrigger>
            }
          >
            {expanded ? <ChevronDown data-icon="inline-start" /> : <ChevronRight data-icon="inline-start" />}
          </TooltipTrigger>
          <TooltipContent>{expanded ? t('collapse') : t('expand')}</TooltipContent>
        </Tooltip>
        <div className="worldbook-entry-toggle-cell" onClick={(event) => event.stopPropagation()}>
          <span className="worldbook-entry-toggle-spinner">
            {busy === 'toggle' ? <LoaderCircle data-icon="inline-start" className="animate-spin" /> : null}
          </span>
          <Field orientation="horizontal" disabled={locked}>
            <Switch checked={draft.enabled} disabled={locked} onCheckedChange={onEnabled} />
            <FieldLabel className="sr-only">
              {t('enabledNamed', { name: draft.name || t('newEntry') })}
            </FieldLabel>
          </Field>
        </div>
        <div className="worldbook-entry-card-title">
          <strong title={draft.name}>{draft.name || t('newEntry')}</strong>
          {error ? (
            <span className="error-text" role="alert">
              {error}
            </span>
          ) : null}
        </div>
        <div className="worldbook-entry-card-actions" onClick={(event) => event.stopPropagation()}>
          {dirty ? <Badge variant="outline">{t('unsaved')}</Badge> : null}
          <Badge variant="outline" className="worldbook-entry-mode-chip">
            {t(draft.activation_mode)}
          </Badge>
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  type="button"
                  variant="destructive"
                  size="icon"
                  aria-label={t('common:delete')}
                  disabled={locked}
                  onClick={onDelete}
                />
              }
            >
              <Trash2 data-icon="inline-start" />
            </TooltipTrigger>
            <TooltipContent>{t('common:delete')}</TooltipContent>
          </Tooltip>
        </div>
      </header>
      <CollapsibleContent
        render={
          <form
            id={`entry-body-${id}`}
            className="worldbook-entry-card-body"
            onSubmit={(event) => {
              event.preventDefault();
              onSave();
            }}
          />
        }
      >
        <FieldSet disabled={!!busy} className="resource-fieldset">
          <div className="worldbook-entry-form-row">
            <Field>
              <FieldLabel>{t('name')}</FieldLabel>
              <Input
                required
                value={draft.name}
                onChange={(event) => onUpdate({ name: event.target.value })}
              />
            </Field>
            <Field>
              <FieldLabel>{t('activationMode')}</FieldLabel>
              <Select
                value={draft.activation_mode}
                onValueChange={(selected) =>
                  onUpdate({ activation_mode: (selected ?? '') as WorldbookEntryInput['activation_mode'] })
                }
                items={[
                  { value: 'keyword', label: t('keyword') },
                  { value: 'always', label: t('always') },
                ]}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="keyword">{t('keyword')}</SelectItem>
                    <SelectItem value="always">{t('always')}</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
          </div>
          <Field>
            <FieldLabel>{t('keywords')}</FieldLabel>
            <Input
              aria-label={t('keywords')}
              aria-describedby={`entry-keywords-help-${id}`}
              maxLength={20000}
              value={draft.keywords_text}
              onChange={(event) => onUpdate({ keywords_text: event.target.value })}
            />
          </Field>
          <small id={`entry-keywords-help-${id}`} className="resource-hint">
            {t('keywordsHelp')}
          </small>
          <Field>
            <FieldLabel>{t('content')}</FieldLabel>
            <Textarea
              required
              rows={8}
              maxLength={200000}
              value={draft.content}
              onChange={(event) => onUpdate({ content: event.target.value })}
            ></Textarea>
          </Field>
          <div className="resource-actions">
            <Button
              type="submit"
              disabled={locked || !draft.name.trim() || !draft.content.trim()}
              variant="default"
            >
              {busy === 'save' ? (
                <LoaderCircle data-icon="inline-start" className="animate-spin" />
              ) : (
                <Save data-icon="inline-start" />
              )}
              {t('common:save')}
            </Button>
            <Button type="button" disabled={!dirty || locked} onClick={onReset} variant="outline">
              <RotateCcw data-icon="inline-start" />
              {t('reset')}
            </Button>
            <Button type="button" disabled={locked} onClick={onDelete} variant="destructive">
              <Trash2 data-icon="inline-start" />
              {t('common:delete')}
            </Button>
          </div>
        </FieldSet>
      </CollapsibleContent>
    </Collapsible>
  );
}
