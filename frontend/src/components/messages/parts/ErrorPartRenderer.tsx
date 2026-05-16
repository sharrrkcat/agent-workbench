import { CircleAlert } from 'lucide-react';
import type { ErrorMessagePart } from '../../../types';

export function ErrorPartRenderer({ part }: { part: ErrorMessagePart }) {
  return (
    <div className="inline-error-block message-error-card">
      <CircleAlert size={16} />
      <div>
        {part.code ? <strong>{part.code}</strong> : null}
        <p>{part.message}</p>
      </div>
    </div>
  );
}
