import { X } from 'lucide-react';
import type { ReactNode } from 'react';
import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

export function AppModal({
  open,
  title,
  subtitle,
  closeLabel,
  width = 'medium',
  closeOnOverlay = true,
  closeOnEscape = true,
  children,
  className = '',
  bodyClassName = '',
  onClose,
}: {
  open: boolean;
  title: ReactNode;
  subtitle?: ReactNode;
  closeLabel: string;
  width?: 'medium' | 'large';
  closeOnOverlay?: boolean;
  closeOnEscape?: boolean;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    window.setTimeout(() => closeButtonRef.current?.focus(), 0);
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && closeOnEscape) {
        onClose();
        return;
      }
      if (event.key !== 'Tab' || !panelRef.current) return;
      const focusable = Array.from(panelRef.current.querySelectorAll<HTMLElement>('button:not(:disabled), [href], input:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])'));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [closeOnEscape, onClose, open]);

  if (!open) return null;

  return createPortal(
    <div
      className="app-modal-overlay"
      role="presentation"
      onMouseDown={() => {
        if (closeOnOverlay) onClose();
      }}
    >
      <section
        className={`app-modal-panel ${width} ${className}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="app-modal-title"
        ref={panelRef}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="app-modal-header">
          <div className="app-modal-title">
            <h2 id="app-modal-title">{title}</h2>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
          <button ref={closeButtonRef} className="settings-secondary-button icon-only" type="button" onClick={onClose} aria-label={closeLabel} title={closeLabel}>
            <X size={16} />
          </button>
        </header>
        <div className={`app-modal-body ${bodyClassName}`}>{children}</div>
      </section>
    </div>,
    document.body,
  );
}
