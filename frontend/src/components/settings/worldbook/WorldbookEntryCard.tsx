import { ChevronDown, ChevronRight, GripVertical, LoaderCircle, RotateCcw, Save, Trash2 } from 'lucide-react';
import type { KeyboardEvent, PointerEvent } from 'react';
import { useTranslation } from 'react-i18next';
import type { WorldbookEntryInput } from '../../../types/worldbook';
import { MiniToggle } from '../../ui/ToggleSwitch';
import { Field, ResourceIcon } from '../resources/ResourceUI';

export function WorldbookEntryCard({ id, draft, expanded, dirty, busy, locked, dragging, error, onToggle, onUpdate, onEnabled,
  onSave, onReset, onDelete, onPointerDown, onPointerMove, onPointerUp, onPointerCancel, onKeyDown }: {
  id: string; draft: WorldbookEntryInput; expanded: boolean; dirty: boolean; busy: string; locked: boolean; dragging: boolean; error?: string;
  onToggle: () => void; onUpdate: (patch: Partial<WorldbookEntryInput>) => void; onEnabled: (enabled: boolean) => void;
  onSave: () => void; onReset: () => void; onDelete: () => void;
  onPointerDown?: (event: PointerEvent<HTMLButtonElement>) => void;
  onPointerMove?: (event: PointerEvent<HTMLButtonElement>) => void;
  onPointerUp?: (event: PointerEvent<HTMLButtonElement>) => void; onPointerCancel?: () => void;
  onKeyDown?: (event: KeyboardEvent<HTMLButtonElement>) => void;
}) {
  const { t } = useTranslation('worldbook');
  return <article data-entry-id={id} className={`worldbook-entry-card${expanded ? ' expanded' : ''}${draft.enabled ? '' : ' disabled'}${dragging ? ' dragging' : ''}`}>
    <header className="worldbook-entry-card-header" onClick={onToggle}>
      <button type="button" className="drag-handle" title={t('dragToReorder')} aria-label={t('dragNamed', { name: draft.name || t('newEntry') })}
        disabled={id === 'new' || locked} onClick={(event) => event.stopPropagation()}
        onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerCancel} onKeyDown={onKeyDown}>
        <GripVertical size={15} />
      </button>
      <button type="button" className="icon-button resource-icon" title={expanded ? t('collapse') : t('expand')}
        aria-label={expanded ? t('collapse') : t('expand')} aria-expanded={expanded} aria-controls={`entry-body-${id}`}
        onClick={(event) => { event.stopPropagation(); onToggle(); }}>{expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</button>
      <div className="worldbook-entry-toggle-cell" onClick={(event) => event.stopPropagation()}>
        <span className="worldbook-entry-toggle-spinner">{busy === 'toggle' ? <LoaderCircle size={14} className="spin" /> : null}</span>
        <MiniToggle checked={draft.enabled} onChange={onEnabled} disabled={locked} label={t('enabledNamed', { name: draft.name || t('newEntry') })} />
      </div>
      <div className="worldbook-entry-card-title"><strong title={draft.name}>{draft.name || t('newEntry')}</strong>
        {error ? <span className="error-text" role="alert">{error}</span> : null}</div>
      <div className="worldbook-entry-card-actions" onClick={(event) => event.stopPropagation()}>
        {dirty ? <span className="resource-badge warning">{t('unsaved')}</span> : null}
        <span className="resource-badge worldbook-entry-mode-chip">{t(draft.activation_mode)}</span>
        <ResourceIcon label={t('common:delete')} danger disabled={locked} onClick={onDelete}><Trash2 size={14} /></ResourceIcon>
      </div>
    </header>
    {expanded ? <form id={`entry-body-${id}`} className="worldbook-entry-card-body" onSubmit={(event) => { event.preventDefault(); onSave(); }}>
      <fieldset disabled={!!busy} className="resource-fieldset">
        <div className="worldbook-entry-form-row">
          <Field label={t('name')}><input required value={draft.name} onChange={(event) => onUpdate({ name: event.target.value })} /></Field>
          <Field label={t('activationMode')}><select value={draft.activation_mode} onChange={(event) => onUpdate({ activation_mode: event.target.value as WorldbookEntryInput['activation_mode'] })}>
            <option value="keyword">{t('keyword')}</option><option value="always">{t('always')}</option>
          </select></Field>
        </div>
        <Field label={t('keywords')}><input aria-label={t('keywords')} aria-describedby={`entry-keywords-help-${id}`} maxLength={20000} value={draft.keywords_text} onChange={(event) => onUpdate({ keywords_text: event.target.value })} /></Field>
        <small id={`entry-keywords-help-${id}`} className="resource-hint">{t('keywordsHelp')}</small>
        <Field label={t('content')}><textarea required rows={8} maxLength={200000} value={draft.content} onChange={(event) => onUpdate({ content: event.target.value })} /></Field>
        <div className="resource-actions">
          <button type="submit" className="primary-button" disabled={locked || !draft.name.trim() || !draft.content.trim()}>
            {busy === 'save' ? <LoaderCircle size={15} className="spin" /> : <Save size={15} />}{t('common:save')}</button>
          <button type="button" className="secondary-button" disabled={!dirty || locked} onClick={onReset}><RotateCcw size={15} />{t('reset')}</button>
          <button type="button" className="secondary-button danger" disabled={locked} onClick={onDelete}><Trash2 size={15} />{t('common:delete')}</button>
        </div>
      </fieldset>
    </form> : null}
  </article>;
}
