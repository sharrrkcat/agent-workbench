import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FieldSet, FieldLegend } from '@/components/ui/field';
import { modelsApi } from '../../../api/models';
import type { SiglipInspection } from '../../../types/models';

export function SiglipInspectionPanel({ modelRef }: { modelRef: string }) {
  const { t } = useTranslation('llm');
  const [information, setInformation] = useState<SiglipInspection | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let cancelled = false;
    void modelsApi.inspectImageEmbedding(modelRef).then((value) => {
      if (!cancelled) setInformation(value);
    }).catch((reason) => {
      if (!cancelled) setError(String(reason.message));
    });
    return () => { cancelled = true; };
  }, [modelRef]);
  const display = (value: unknown) => value == null ? t('siglip.pending')
    : typeof value === 'boolean' ? t(value ? 'enabled' : 'disabled')
    : typeof value === 'object' ? JSON.stringify(value) : String(value);
  const fields = information ? [
    ['structure', information.structure ? t('siglip.structures.' + information.structure) : null],
    ['imageDimensions', information.image.dimensions],
    ['textDimensions', information.text.dimensions],
    ['textLimit', information.text.max_position_embeddings],
    ['imageSize', information.processor.size ?? information.image.image_size],
    ['patchSize', information.processor.patch_size ?? information.image.patch_size],
    ['maxPatches', information.processor.max_num_patches],
    ['resample', information.processor.resample],
    ['rescale', information.processor.do_rescale],
    ['rescaleFactor', information.processor.rescale_factor],
    ['normalize', information.processor.do_normalize],
    ['imageMean', information.processor.image_mean],
    ['imageStd', information.processor.image_std],
    ['lowercase', information.text.do_lower_case],
    ['bos', information.text.add_bos_token],
    ['eos', information.text.add_eos_token],
  ] as const : [];
  return (
    <FieldSet aria-label={t('siglip.information')}>
      <FieldLegend>{t('siglip.information')}</FieldLegend>
      <p className="text-sm text-muted-foreground">{t('siglip.informationHint')}</p>
      {error ? <p role="status">{t('siglip.inspectionFailed')} {error}</p>
        : !information ? <p role="status">{t('siglip.inspecting')}</p> : null}
      {information ? <>
        <dl className="grid min-w-0 gap-3 text-sm sm:grid-cols-2">
          {fields.map(([key, value]) => <div key={key} className="min-w-0">
            <dt className="text-muted-foreground">{t('siglip.fields.' + key)}</dt>
            <dd className="wrap-anywhere">{display(value)}</dd>
          </div>)}
        </dl>
        {information.structure === 'fixres' ? <p className="text-sm text-muted-foreground">{t('siglip.fixresHint')}</p> : null}
        {information.diagnostics.length ? <ul className="flex flex-col gap-1 text-sm" role="status">
          {information.diagnostics.map((diagnostic, index) => <li key={index}>
            <code>{diagnostic.file}</code>: {t('siglip.diagnostics.' + diagnostic.code)}
          </li>)}
        </ul> : null}
      </> : null}
    </FieldSet>
  );
}
