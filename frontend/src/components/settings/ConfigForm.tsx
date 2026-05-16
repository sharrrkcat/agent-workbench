import { useTranslation } from 'react-i18next';
import type { ConfigFieldSchema } from '../../types';
import type { ConfigValues } from './configUtils';
import { SecretInput, MASKED_SECRET_VALUE } from './SecretInput';
import { ToggleSwitch } from './ToggleSwitch';

export function ConfigForm({
  fields,
  values,
  onChange,
  emptyMessage,
}: {
  fields: ConfigFieldSchema[];
  values: ConfigValues;
  onChange: (values: ConfigValues) => void;
  emptyMessage: string;
}) {
  if (!fields.length) {
    return <div className="settings-empty-state">{emptyMessage}</div>;
  }

  return (
    <div className="settings-config-form">
      {fields.map((field) => (
        <ConfigFieldEditor
          key={field.name}
          field={field}
          value={values[field.name]}
          onChange={(value) => onChange({ ...values, [field.name]: value })}
        />
      ))}
    </div>
  );
}

function ConfigFieldEditor({
  field,
  value,
  onChange,
}: {
  field: ConfigFieldSchema;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const { t } = useTranslation(['capabilities', 'common']);
  const label = t(`capabilities:configFields.${field.name}.label`, { defaultValue: field.label || field.name });
  const description = t(`capabilities:configFields.${field.name}.description`, { defaultValue: field.description || '' });
  const requiredLabel = t('common:required', { defaultValue: 'required' });
  const id = `settings-config-${field.name}`;
  if (field.type === 'boolean') {
    return (
      <div className="config-field settings-config-field boolean-field">
        <span>
          {label}
          {field.required ? <em>{requiredLabel}</em> : null}
        </span>
        <ToggleSwitch checked={Boolean(value)} onChange={onChange} />
        {description ? <small>{description}</small> : null}
      </div>
    );
  }
  if (field.secret) {
    const stringValue = String(value ?? '');
    const hasSecret = stringValue === MASKED_SECRET_VALUE;
    return (
      <SecretInput
        id={id}
        label={label}
        required={field.required}
        value={hasSecret ? '' : stringValue}
        hasSecret={hasSecret}
        onChange={onChange}
      />
    );
  }
  return (
    <label className="config-field settings-config-field" htmlFor={id}>
      <span>
        {label}
        {field.required ? <em>{requiredLabel}</em> : null}
      </span>
      {renderInput(field, id, value, onChange)}
      {description ? <small>{description}</small> : null}
    </label>
  );
}

function renderInput(field: ConfigFieldSchema, id: string, value: unknown, onChange: (value: unknown) => void) {
  if (field.type === 'text') {
    return <textarea id={id} rows={4} value={String(value ?? '')} onChange={(event) => onChange(event.target.value)} />;
  }
  if (field.type === 'integer' || field.type === 'float') {
    return <input id={id} type="number" value={String(value ?? '')} onChange={(event) => onChange(event.target.value)} />;
  }
  if (field.type === 'enum') {
    const optionValues = new Set(field.options);
    const selected = typeof value === 'string' && optionValues.has(value) ? value : String(field.default ?? '');
    return (
      <select id={id} value={selected} onChange={(event) => onChange(event.target.value)}>
        {field.options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    );
  }
  if (field.type === 'json') {
    if (Array.isArray(field.default)) {
      return (
        <textarea
          id={id}
          rows={Math.min(10, Math.max(4, Array.isArray(value) ? value.length : 4))}
          value={Array.isArray(value) ? value.join('\n') : String(value ?? '')}
          onChange={(event) => onChange(event.target.value)}
          spellCheck={false}
        />
      );
    }
    return (
      <textarea
        id={id}
        rows={6}
        value={typeof value === 'string' ? value : JSON.stringify(value ?? {}, null, 2)}
        onChange={(event) => onChange(event.target.value)}
        spellCheck={false}
      />
    );
  }
  return (
    <input
      id={id}
      type="text"
      value={String(value ?? '')}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}
