import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Input } from '@/components/ui/input';
import { Field, FieldLabel } from '@/components/ui/field';
import { useRef } from 'react';
import { useTranslation } from 'react-i18next';

export function CudaLayersField({
  value,
  onChange,
}: {
  value: 'auto' | number;
  onChange: (value: 'auto' | number) => void;
}) {
  const { t } = useTranslation('llm');
  const manual = useRef(typeof value === 'number' ? value : 1);
  const automatic = value === 'auto';
  if (!automatic) manual.current = value;
  return (
    <div className="runtime-gpu-field">
      <span>{t('gpuAllocation')}</span>
      <ToggleGroup
        className="runtime-gpu-mode"
        aria-label={t('gpuAllocation')}
        multiple={false}
        value={[automatic ? 'auto' : 'manual']}
        onValueChange={(next) => {
          if (next.length) onChange(next[0] === 'auto' ? 'auto' : manual.current);
        }}
      >
        <ToggleGroupItem value="auto">{t('gpuAuto')}</ToggleGroupItem>
        <ToggleGroupItem value="manual">{t('gpuManual')}</ToggleGroupItem>
      </ToggleGroup>
      {!automatic ? (
        <Field>
          <FieldLabel>{t('runtimeParams.gpu_layers')}</FieldLabel>
          <Input
            type="number"
            min={1}
            max={999}
            step={1}
            value={Number.isNaN(value) ? '' : (value ?? '')}
            onChange={(event) =>
              onChange(event.currentTarget.value === '' ? 1 : Number(event.currentTarget.value))
            }
          />
        </Field>
      ) : null}
    </div>
  );
}
