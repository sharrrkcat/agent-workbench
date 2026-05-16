import type { ReactNode } from 'react';
import type { JsonMessagePart } from '../../../types';

export function JsonPartRenderer({ part, renderJson }: { part: JsonMessagePart; renderJson: (data: unknown) => ReactNode }) {
  return <>{renderJson(part.data)}</>;
}
