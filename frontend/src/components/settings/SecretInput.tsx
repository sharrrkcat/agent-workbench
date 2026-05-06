import { Eye, EyeOff } from 'lucide-react';
import { useEffect, useState } from 'react';

export const MASKED_SECRET_VALUE = '********';

export function SecretInput({
  id,
  label,
  hasSecret,
  value,
  onChange,
  disabled = false,
  required = false,
}: {
  id?: string;
  label: string;
  hasSecret: boolean;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  required?: boolean;
}) {
  const [revealDraft, setRevealDraft] = useState(false);

  useEffect(() => {
    if (!value) setRevealDraft(false);
  }, [value]);

  return (
    <div className="config-field settings-config-field secret-field">
      <span>
        {label}
        {required ? <em>required</em> : null}
      </span>
      <div className="secret-input-row">
        <input
          id={id}
          type={value && revealDraft ? 'text' : 'password'}
          value={value}
          placeholder={hasSecret ? 'API key saved' : 'Optional API key'}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          autoComplete="off"
          spellCheck={false}
        />
        {value ? (
          <button
            type="button"
            className="secret-input-icon-button"
            onClick={() => setRevealDraft((current) => !current)}
            disabled={disabled}
            title={revealDraft ? 'Hide new API key' : 'Show new API key'}
            aria-label={revealDraft ? 'Hide new API key' : 'Show new API key'}
          >
            {revealDraft ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        ) : null}
      </div>
    </div>
  );
}
