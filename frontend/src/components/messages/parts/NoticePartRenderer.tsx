import type { NoticeMessagePart } from '../../../types';

export function NoticePartRenderer({ part }: { part: NoticeMessagePart }) {
  return <div className={`message-content message-part-notice ${part.level}`}>{part.text}</div>;
}
