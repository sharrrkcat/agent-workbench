import { useLayoutEffect, useRef, useState } from 'react';

/** Measure against the compact width so expanding cannot immediately collapse the composer. */
export function useComposerLayout(draft: string) {
  const composerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);
  const measureLayout = useRef<() => void>(() => {});
  const [layout, setLayout] = useState({ expanded: false, textHeight: 56 });

  useLayoutEffect(() => {
    const composer = composerRef.current!;
    const textarea = textareaRef.current!;
    const mirror = measureRef.current!;
    function measure() {
      // The retained chat can be hidden while another page is open.
      if (!composer.clientWidth) return;
      const style = getComputedStyle(textarea);
      Object.assign(mirror.style, {
        font: style.font,
        letterSpacing: style.letterSpacing,
        wordSpacing: style.wordSpacing,
        tabSize: style.tabSize,
        textIndent: style.textIndent,
        textTransform: style.textTransform,
        direction: style.direction,
        whiteSpace: style.whiteSpace,
        overflowWrap: style.overflowWrap,
        wordBreak: style.wordBreak,
      });
      // A zero-width trailing character preserves the height of a final empty line.
      mirror.textContent = textarea.value + '\u200b';
      const inset = parseFloat(style.getPropertyValue('--composer-inline-inset'));
      mirror.style.width = `${Math.max(1, composer.clientWidth - inset * 2)}px`;
      const expanded = /[\r\n]/.test(textarea.value)
        || (!!textarea.value && mirror.getBoundingClientRect().height > parseFloat(style.lineHeight) + 1);
      mirror.style.width = `${Math.max(1, composer.clientWidth - 24)}px`;
      const textHeight = Math.max(56, Math.ceil(mirror.getBoundingClientRect().height + 20));
      setLayout((previous) => previous.expanded === expanded && previous.textHeight === textHeight
        ? previous : { expanded, textHeight });
    }
    measureLayout.current = measure;
    measure();
    let width = composer.clientWidth;
    const observer = new ResizeObserver(() => {
      if (composer.clientWidth === width) return;
      width = composer.clientWidth;
      measure();
    });
    observer.observe(composer);
    window.addEventListener('resize', measure);
    document.fonts.addEventListener('loadingdone', measure);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', measure);
      document.fonts.removeEventListener('loadingdone', measure);
    };
  }, []);

  useLayoutEffect(() => { measureLayout.current(); }, [draft]);

  return { composerRef, textareaRef, measureRef, ...layout };
}
