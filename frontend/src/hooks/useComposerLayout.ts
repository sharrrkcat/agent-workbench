import { useLayoutEffect, useRef, useState } from 'react';

/** Measure against the compact width so expanding cannot immediately collapse the composer. */
export function useComposerLayout(draft: string, fullPlaceholder: string, shortPlaceholder: string, expandPlaceholder = false) {
  const composerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);
  const actionsRef = useRef<HTMLDivElement>(null);
  const leadingActionsRef = useRef<HTMLDivElement>(null);
  const measureLayout = useRef<() => void>(() => {});
  const placeholders = useRef([fullPlaceholder, shortPlaceholder]);
  placeholders.current = [fullPlaceholder, shortPlaceholder];
  const [layout, setLayout] = useState({ expanded: false, textHeight: 56, placeholder: fullPlaceholder });

  useLayoutEffect(() => {
    const composer = composerRef.current!;
    const textarea = textareaRef.current!;
    const mirror = measureRef.current!;
    const actions = actionsRef.current!;
    const leadingActions = leadingActionsRef.current;
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
      const start = leadingActions ? leadingActions.getBoundingClientRect().width + 20
        : parseFloat(style.getPropertyValue('--composer-inline-start'));
      if (leadingActions) composer.style.setProperty('--composer-inline-start', `${start}px`);
      const end = actions.getBoundingClientRect().width + 20;
      composer.style.setProperty('--composer-inline-end', `${end}px`);
      const available = Math.max(1, composer.clientWidth - start - end);
      mirror.style.width = 'max-content';
      mirror.style.whiteSpace = 'pre';
      const placeholder = expandPlaceholder ? placeholders.current[0] : placeholders.current.find((value) => {
        mirror.textContent = value;
        return mirror.getBoundingClientRect().width <= available;
      }) ?? '';
      mirror.style.whiteSpace = style.whiteSpace;
      // A zero-width trailing character preserves the height of a final empty line.
      const text = textarea.value || (expandPlaceholder ? placeholder : '');
      mirror.textContent = text + '\u200b';
      mirror.style.width = `${available}px`;
      const expanded = /[\r\n]/.test(text)
        || (!!text && mirror.getBoundingClientRect().height > parseFloat(style.lineHeight) + 1);
      mirror.style.width = `${Math.max(1, composer.clientWidth - 24)}px`;
      const textHeight = Math.max(56, Math.ceil(mirror.getBoundingClientRect().height + 20));
      setLayout((previous) => previous.expanded === expanded && previous.textHeight === textHeight && previous.placeholder === placeholder
        ? previous : { expanded, textHeight, placeholder });
    }
    measureLayout.current = measure;
    measure();
    let width = composer.clientWidth;
    let actionsWidth = actions.clientWidth;
    let leadingWidth = leadingActions?.clientWidth;
    const observer = new ResizeObserver(() => {
      if (composer.clientWidth === width && actions.clientWidth === actionsWidth && leadingActions?.clientWidth === leadingWidth) return;
      width = composer.clientWidth;
      actionsWidth = actions.clientWidth;
      leadingWidth = leadingActions?.clientWidth;
      measure();
    });
    observer.observe(composer);
    observer.observe(actions);
    if (leadingActions) observer.observe(leadingActions);
    window.addEventListener('resize', measure);
    document.fonts.addEventListener('loadingdone', measure);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', measure);
      document.fonts.removeEventListener('loadingdone', measure);
    };
  }, [expandPlaceholder]);

  useLayoutEffect(() => { measureLayout.current(); }, [draft, fullPlaceholder, shortPlaceholder]);

  return { composerRef, textareaRef, measureRef, actionsRef, leadingActionsRef, ...layout };
}
