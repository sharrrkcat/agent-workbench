import { Input } from '@/components/ui/input';
import { FieldGroup, Field, FieldLabel } from '@/components/ui/field';
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectGroup,
  SelectItem,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { useTranslation } from 'react-i18next';
import type { ModelInput } from '../../../types/models';

import { localEngine, selectTTSArchitecture, ttsGenerationDefaults } from './profileDefaults';

export function ProfileParameters({
  value,
  onChange,
}: {
  value: ModelInput;
  onChange: (parameters: ModelInput['parameters']) => void;
}) {
  const { t } = useTranslation('llm');
  const patchParam = (key: string, next: unknown) => onChange({ ...value.parameters, [key]: next });
  // Viewport columns need no size containment, which can hide unchanged fields
  // in Chromium when an architecture removes sibling controls.
  return (
    <FieldGroup className="@container-normal grid gap-4 sm:grid-cols-2">
      {value.kind === 'llm' ? (
        <>
          {[
            ['temperature', 0, 2, 0.1],
            ['top_p', 0, 1, 0.05],
            ['max_tokens', 1, undefined, 1],
            ['presence_penalty', -2, 2, 0.1],
            ['frequency_penalty', -2, 2, 0.1],
            ['seed', undefined, undefined, 1],
          ]
            .filter(
              ([key]) =>
                localEngine(value) !== 'transformers' ||
                !['presence_penalty', 'frequency_penalty'].includes(String(key)),
            )
            .map(([key, min, max, step]) => (
              <Field key={String(key)}>
                <FieldLabel>{t('params.' + key)}</FieldLabel>
                <Input
                  type="number"
                  min={min as number}
                  max={max as number}
                  step={step as number}
                  value={
                    Number.isNaN(value.parameters[String(key)] as number | undefined)
                      ? ''
                      : ((value.parameters[String(key)] as number | undefined) ?? '')
                  }
                  onChange={(event) =>
                    patchParam(
                      String(key),
                      event.currentTarget.value === '' ? null : Number(event.currentTarget.value),
                    )
                  }
                />
              </Field>
            ))}
          <Field>
            <FieldLabel>{t('params.stop')}</FieldLabel>
            <Input
              value={String(value.parameters.stop || '')}
              onChange={(e) => patchParam('stop', e.target.value || null)}
            />
          </Field>
        </>
      ) : value.kind === 'tts' ? (
        <>
          <Field>
            <FieldLabel>{t('params.architecture')}</FieldLabel>
            <Select
              value={String(value.parameters.architecture ?? 'kokoro')}
              onValueChange={(selected) =>
                onChange(
                  selectTTSArchitecture(
                    value.parameters,
                    (selected ?? '') as keyof typeof ttsGenerationDefaults,
                  ),
                )
              }
              items={[
                { value: 'kokoro', label: <>Kokoro-82M v1.0 (ONNX)</> },
                { value: 'chatterbox', label: t('chatterboxEnglish') },
                { value: 'qwen3tts', label: t('qwen3TTSBase') },
              ]}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="kokoro">Kokoro-82M v1.0 (ONNX)</SelectItem>
                  <SelectItem value="chatterbox">{t('chatterboxEnglish')}</SelectItem>
                  <SelectItem value="qwen3tts">{t('qwen3TTSBase')}</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
          {['chatterbox', 'qwen3tts'].includes(String(value.parameters.architecture)) ? (
            <Field>
              <FieldLabel>{t('params.seed')}</FieldLabel>
              <Input
                type="number"
                min={0}
                max={4294967295}
                step={1}
                value={
                  Number.isNaN(value.parameters.seed as number | null | undefined)
                    ? ''
                    : ((value.parameters.seed as number | null | undefined) ?? '')
                }
                onChange={(event) =>
                  patchParam(
                    'seed',
                    event.currentTarget.value === '' ? null : Number(event.currentTarget.value),
                  )
                }
              />
            </Field>
          ) : null}
          {value.parameters.architecture === 'chatterbox'
            ? [
                ['exaggeration', 0.5, 0, 2, 0.05],
                ['cfg_weight', 0.5, 0, 1, 0.05],
                ['temperature', 0.8, 0.01, 5, 0.01],
                ['repetition_penalty', 1.2, 1, 2, 0.05],
                ['min_p', 0.05, 0, 1, 0.01],
                ['top_p', 1, 0.01, 1, 0.01],
              ].map(([key, initial, min, max, step]) => (
                <Field key={String(key)}>
                  <FieldLabel>{t('params.' + key)}</FieldLabel>
                  <Input
                    type="number"
                    min={Number(min)}
                    max={Number(max)}
                    step={Number(step)}
                    value={
                      Number.isNaN(Number(value.parameters[String(key)] ?? initial))
                        ? ''
                        : (Number(value.parameters[String(key)] ?? initial) ?? '')
                    }
                    onChange={(event) =>
                      patchParam(
                        String(key),
                        event.currentTarget.value === '' ? initial : Number(event.currentTarget.value),
                      )
                    }
                  />
                </Field>
              ))
            : null}
          {value.parameters.architecture === 'qwen3tts' ? (
            <>
              <Field orientation="horizontal">
                <Switch
                  checked={value.parameters.do_sample !== false}
                  onCheckedChange={(next) => patchParam('do_sample', next)}
                />
                <FieldLabel>{t('params.do_sample')}</FieldLabel>
              </Field>
              {(
                [
                  ['temperature', 0.01, undefined, 0.01],
                  ['top_p', 0.01, 1, 0.01],
                  ['top_k', 0, undefined, 1],
                  ['repetition_penalty', 0.01, undefined, 0.01],
                  ['max_new_tokens', 1, 8192, 1],
                ] as const
              ).map(([key, min, max, step]) => (
                <Field key={key}>
                  <FieldLabel>{t('params.' + key)}</FieldLabel>
                  <Input
                    type="number"
                    min={min}
                    max={max}
                    step={step}
                    value={
                      Number.isNaN(Number(value.parameters[key] ?? ttsGenerationDefaults.qwen3tts[key]))
                        ? ''
                        : (Number(value.parameters[key] ?? ttsGenerationDefaults.qwen3tts[key]) ?? '')
                    }
                    onChange={(event) =>
                      patchParam(
                        key,
                        event.currentTarget.value === ''
                          ? ttsGenerationDefaults.qwen3tts[key]
                          : Number(event.currentTarget.value),
                      )
                    }
                  />
                </Field>
              ))}
            </>
          ) : null}
          <Field>
            <FieldLabel>{t('params.speed')}</FieldLabel>
            <Input
              type="number"
              min={0.25}
              max={4}
              step={0.05}
              value={
                Number.isNaN(Number(value.parameters.speed ?? 1))
                  ? ''
                  : (Number(value.parameters.speed ?? 1) ?? '')
              }
              onChange={(event) =>
                patchParam('speed', event.currentTarget.value === '' ? 1 : Number(event.currentTarget.value))
              }
            />
          </Field>
          <Field>
            <FieldLabel>{t('params.response_format')}</FieldLabel>
            <Select
              value={String(value.parameters.response_format ?? 'mp3')}
              onValueChange={(selected) => patchParam('response_format', selected ?? '')}
              items={[
                { value: 'mp3', label: <>MP3</> },
                { value: 'wav', label: <>WAV</> },
              ]}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectGroup>
                  <SelectItem value="mp3">MP3</SelectItem>
                  <SelectItem value="wav">WAV</SelectItem>
                </SelectGroup>
              </SelectContent>
            </Select>
          </Field>
        </>
      ) : (
        <>
          <Field>
            <FieldLabel>{t('params.batch_size')}</FieldLabel>
            <Input
              type="number"
              min={1}
              step={1}
              value={
                Number.isNaN(
                  Number(
                    value.parameters.batch_size ||
                      (value.kind === 'embedding' || value.kind === 'reranker' ? 16 : 1),
                  ),
                )
                  ? ''
                  : (Number(
                      value.parameters.batch_size ||
                        (value.kind === 'embedding' || value.kind === 'reranker' ? 16 : 1),
                    ) ?? '')
              }
              onChange={(event) =>
                patchParam(
                  'batch_size',
                  event.currentTarget.value === '' ? 1 : Number(event.currentTarget.value),
                )
              }
            />
          </Field>
          {['embedding', 'image_embedding'].includes(value.kind) ? (
            <>
              <Field>
                <FieldLabel>{t('params.dimensions')}</FieldLabel>
                <Input
                  type="number"
                  min={1}
                  step={1}
                  value={
                    Number.isNaN(value.parameters.dimensions as number | undefined)
                      ? ''
                      : ((value.parameters.dimensions as number | undefined) ?? '')
                  }
                  onChange={(event) =>
                    patchParam(
                      'dimensions',
                      event.currentTarget.value === '' ? null : Number(event.currentTarget.value),
                    )
                  }
                />
              </Field>
              <Field orientation="horizontal">
                <Switch
                  checked={value.parameters.normalize !== false}
                  onCheckedChange={(v) => patchParam('normalize', v)}
                />
                <FieldLabel>{t('params.normalize')}</FieldLabel>
              </Field>
            </>
          ) : null}
          {value.kind === 'embedding' ? (
            <>
              {['document_instruction', 'query_instruction'].map((key) => (
                <Field key={key}>
                  <FieldLabel>{t('params.' + key)}</FieldLabel>
                  <Textarea
                    rows={2}
                    value={String(value.parameters[key] || '')}
                    onChange={(e) => patchParam(key, e.target.value)}
                  ></Textarea>
                </Field>
              ))}
            </>
          ) : null}
          {value.kind === 'image_embedding' || value.kind === 'vision' ? (
            <Field>
              <FieldLabel>{t('params.architecture')}</FieldLabel>
              <Select
                value={String(value.parameters.architecture || (value.kind === 'vision' ? 'wd14' : 'clip'))}
                onValueChange={(selected) => patchParam('architecture', selected ?? '')}
                items={(value.kind === 'vision' ? ['wd14'] : ['clip', 'siglip2']).map((v) => ({
                  value: v,
                  label: v,
                }))}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {(value.kind === 'vision' ? ['wd14'] : ['clip', 'siglip2']).map((v) => (
                      <SelectItem key={v} value={v}>
                        {v}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
          ) : null}
          {value.kind === 'vision' ? (
            <Field>
              <FieldLabel>{t('params.task')}</FieldLabel>
              <Select value={'tags'} disabled={true} items={[{ value: 'tags', label: t('visionTags') }]}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectItem value="tags">{t('visionTags')}</SelectItem>
                  </SelectGroup>
                </SelectContent>
              </Select>
            </Field>
          ) : null}
        </>
      )}
    </FieldGroup>
  );
}
