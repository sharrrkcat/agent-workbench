import { useTranslation } from 'react-i18next';
import type { ModelInput } from '../../../types/models';
import { Check, Field, NumberInput } from './fields';

export function ProfileParameters({
  value,
  onChange,
}: {
  value: ModelInput;
  onChange: (parameters: ModelInput['parameters']) => void;
}) {
  const { t } = useTranslation('llm');
  const patchParam = (key: string, next: unknown) => onChange({ ...value.parameters, [key]: next });
  return (
    <div className="model-form-grid">
      {value.kind === 'llm' ? (
        <>
          {[
            ['temperature', 0, 2, 0.1],
            ['top_p', 0, 1, 0.05],
            ['max_tokens', 1, undefined, 1],
            ['presence_penalty', -2, 2, 0.1],
            ['frequency_penalty', -2, 2, 0.1],
            ['seed', undefined, undefined, 1],
          ].map(([key, min, max, step]) => (
            <NumberInput
              key={String(key)}
              label={t('params.' + key)}
              value={value.parameters[String(key)] as number | undefined}
              min={min as number}
              max={max as number}
              step={step as number}
              onChange={(v) => patchParam(String(key), v)}
            />
          ))}
          <Field label={t('params.stop')}>
            <input
              value={String(value.parameters.stop || '')}
              onChange={(e) => patchParam('stop', e.target.value || null)}
            />
          </Field>
        </>
      ) : value.kind === 'tts' ? (
        <>
          <Field label={t('params.architecture')}>
            <select value="kokoro" disabled><option value="kokoro">Kokoro-82M v1.0 (ONNX)</option></select>
          </Field>
          <NumberInput label={t('params.speed')} value={Number(value.parameters.speed ?? 1)} min={0.25} max={4} step={0.05}
            onChange={(speed) => patchParam('speed', speed ?? 1)} />
          <Field label={t('params.response_format')}>
            <select value={String(value.parameters.response_format ?? 'mp3')} onChange={(e) => patchParam('response_format', e.target.value)}>
              <option value="mp3">MP3</option><option value="wav">WAV</option>
            </select>
          </Field>
        </>
      ) : (
        <>
          <NumberInput
            label={t('params.batch_size')}
            value={Number(
              value.parameters.batch_size || (value.kind === 'embedding' || value.kind === 'reranker' ? 16 : 1),
            )}
            min={1}
            onChange={(v) => patchParam('batch_size', v ?? 1)}
          />
          {['embedding', 'image_embedding'].includes(value.kind) ? (
            <>
              <NumberInput
                label={t('params.dimensions')}
                value={value.parameters.dimensions as number | undefined}
                min={1}
                onChange={(v) => patchParam('dimensions', v)}
              />
              <Check
                label={t('params.normalize')}
                checked={value.parameters.normalize !== false}
                onChange={(v) => patchParam('normalize', v)}
              />
            </>
          ) : null}
          {value.kind === 'embedding' ? (
            <>
              {['document_instruction', 'query_instruction'].map((key) => (
                <Field key={key} label={t('params.' + key)}>
                  <textarea
                    rows={2}
                    value={String(value.parameters[key] || '')}
                    onChange={(e) => patchParam(key, e.target.value)}
                  />
                </Field>
              ))}
            </>
          ) : null}
          {value.kind === 'image_embedding' || value.kind === 'vision' ? (
            <Field label={t('params.architecture')}>
              <select
                value={String(value.parameters.architecture || (value.kind === 'vision' ? 'florence2' : 'clip'))}
                onChange={(e) => patchParam('architecture', e.target.value)}
              >
                {(value.kind === 'vision' ? ['florence2', 'wd14'] : ['clip', 'siglip2', 'dinov2']).map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </Field>
          ) : null}
          {value.kind === 'vision' ? (
            <Field label={t('params.task')}>
              <input
                value={String(value.parameters.task || 'caption')}
                onChange={(e) => patchParam('task', e.target.value)}
              />
            </Field>
          ) : null}
        </>
      )}
    </div>
  );
}
