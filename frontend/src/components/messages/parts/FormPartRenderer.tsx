import type { ReactNode } from 'react';
import type { ActionFormBlock, FormMessagePart } from '../../../types';

export function FormPartRenderer({
  part,
  partIndex,
  renderForm,
}: {
  part: FormMessagePart;
  partIndex: number;
  renderForm: (form: ActionFormBlock, blockIndex: number) => ReactNode;
}) {
  return <>{renderForm({ ...part, type: 'action_form' }, partIndex)}</>;
}
