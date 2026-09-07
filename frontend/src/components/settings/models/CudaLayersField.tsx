import { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { NumberInput } from './fields';

export function CudaLayersField({ value, onChange }: {
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
      <div className="runtime-gpu-mode" role="group" aria-label={t('gpuAllocation')}>
        <button type="button" aria-pressed={automatic} onClick={() => onChange('auto')}>{t('gpuAuto')}</button>
        <button type="button" aria-pressed={!automatic} onClick={() => onChange(manual.current)}>{t('gpuManual')}</button>
      </div>
      {!automatic ? <NumberInput label={t('runtimeParams.gpu_layers')} value={value} min={1} max={999}
        onChange={(next) => onChange(next ?? 1)} /> : null}
    </div>
  );
}
