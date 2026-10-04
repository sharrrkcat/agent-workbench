import type { ComponentProps, CSSProperties } from 'react';
import { InputGroup, InputGroupAddon, InputGroupTextarea } from '@/components/ui/input-group';

export function ComposerSurface({ expanded, textHeight, ...props }: ComponentProps<typeof InputGroup> & { expanded: boolean; textHeight: number }) {
  return <InputGroup {...props} data-expanded={expanded}
    className="composer block rounded-[20px] has-[textarea]:rounded-[20px] has-data-[align=block-end]:rounded-[20px] transition-[height] duration-180 ease-out motion-reduce:transition-none"
    style={{ '--composer-text-height': `min(${textHeight}px, 12rem, 30dvh)`,
      height: expanded ? 'calc(var(--composer-text-height) + var(--composer-toolbar-height) + 2px)' : 'calc(var(--composer-compact-height) + 2px)',
    } as CSSProperties} />;
}

export function ComposerTextarea({ expanded, ...props }: ComponentProps<typeof InputGroupTextarea> & { expanded: boolean }) {
  return <InputGroupTextarea {...props}
    className="min-h-0 [field-sizing:fixed] transition-[height,padding] duration-180 ease-out motion-reduce:transition-none"
    style={{ height: expanded ? 'var(--composer-text-height)' : 'var(--composer-compact-height)',
      paddingInlineStart: expanded ? '12px' : 'var(--composer-inline-start)',
      paddingInlineEnd: expanded ? '12px' : 'var(--composer-inline-end)',
      paddingBlock: expanded ? '10px' : 'calc((var(--composer-compact-height) - 1lh) / 2)',
      overflowY: expanded ? 'auto' : 'hidden',
    }} />;
}

export function ComposerToolbar(props: ComponentProps<typeof InputGroupAddon>) {
  return <InputGroupAddon {...props} align="block-end"
    className="composer-toolbar absolute inset-x-0 bottom-0 gap-2 pt-1 pointer-events-none [&_button]:pointer-events-auto" />;
}
