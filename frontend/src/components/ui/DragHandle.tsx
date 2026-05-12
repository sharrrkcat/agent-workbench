import { GripVertical } from 'lucide-react';
import type { DragEventHandler, MouseEventHandler } from 'react';

export function DragHandle({
  draggable,
  disabled,
  title,
  onDragStart,
  onDragEnd,
  onClick,
}: {
  draggable?: boolean;
  disabled?: boolean;
  title: string;
  onDragStart?: DragEventHandler<HTMLButtonElement>;
  onDragEnd?: DragEventHandler<HTMLButtonElement>;
  onClick?: MouseEventHandler<HTMLButtonElement>;
}) {
  return (
    <button
      className="drag-handle"
      type="button"
      draggable={draggable}
      disabled={disabled}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onClick}
      title={title}
      aria-label={title}
    >
      <GripVertical size={15} aria-hidden="true" />
    </button>
  );
}
