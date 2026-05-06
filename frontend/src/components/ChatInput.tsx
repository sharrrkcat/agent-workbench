import { FormEvent, KeyboardEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { AtSign, Loader2, Paperclip, Send, Slash } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { CommandPalette } from './CommandPalette';

export function ChatInput() {
  const [value, setValue] = useState('');
  const [cursorPosition, setCursorPosition] = useState(0);
  const [suggestionsDismissed, setSuggestionsDismissed] = useState(false);
  const formRef = useRef<HTMLFormElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const { currentSession, sendMessage, sending } = useWorkbenchStore();

  const canSend = Boolean(currentSession && value.trim() && !sending);

  const activeToken = useMemo(() => getActiveToken(value, cursorPosition), [cursorPosition, value]);
  const mode = useMemo(() => {
    if (!activeToken || suggestionsDismissed) return 'none';
    if (activeToken.token.startsWith('/')) return 'commands';
    if (activeToken.token.startsWith('@') && activeToken.token.includes(':')) return 'actions';
    if (activeToken.token.startsWith('@')) return 'agents';
    return 'none';
  }, [activeToken, suggestionsDismissed]);

  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    const nextHeight = Math.min(textarea.scrollHeight, 180);
    textarea.style.height = `${Math.max(nextHeight, 44)}px`;
    textarea.style.overflowY = textarea.scrollHeight > 180 ? 'auto' : 'hidden';
  }, [value]);

  useEffect(() => {
    setSuggestionsDismissed(false);
  }, [cursorPosition, value]);

  useEffect(() => {
    function onPointerDown(event: PointerEvent) {
      if (!formRef.current?.contains(event.target as Node)) {
        setSuggestionsDismissed(true);
      }
    }
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, []);

  function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!canSend) return;
    const content = value;
    setValue('');
    setCursorPosition(0);
    setSuggestionsDismissed(true);
    void sendMessage(content);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Escape' && mode !== 'none') {
      event.preventDefault();
      setSuggestionsDismissed(true);
      return;
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  function updateValue(nextValue: string, nextCursor: number) {
    setValue(nextValue);
    setCursorPosition(nextCursor);
  }

  function pickSuggestion(replacement: string) {
    if (!activeToken) return;
    const nextValue = `${value.slice(0, activeToken.start)}${replacement}${value.slice(activeToken.end)}`;
    const nextCursor = activeToken.start + replacement.length;
    setValue(nextValue);
    setCursorPosition(nextCursor);
    setSuggestionsDismissed(true);
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(nextCursor, nextCursor);
    });
  }

  function insertTrigger(trigger: '@' | '/') {
    const textarea = textareaRef.current;
    const position = textarea?.selectionStart ?? cursorPosition;
    const needsSpace = value && position > 0 && !/\s/.test(value[position - 1]);
    const insertion = `${needsSpace ? ' ' : ''}${trigger}`;
    const nextValue = `${value.slice(0, position)}${insertion}${value.slice(position)}`;
    const nextCursor = position + insertion.length;
    setValue(nextValue);
    setCursorPosition(nextCursor);
    setSuggestionsDismissed(false);
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      textareaRef.current?.setSelectionRange(nextCursor, nextCursor);
    });
  }

  return (
    <form ref={formRef} className="composer-shell" onSubmit={submit}>
      <div className="composer-card">
        <CommandPalette mode={mode} token={activeToken?.token ?? ''} onPick={pickSuggestion} />
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => updateValue(event.target.value, event.target.selectionStart)}
          onKeyDown={onKeyDown}
          onKeyUp={(event) => setCursorPosition(event.currentTarget.selectionStart)}
          onSelect={(event) => setCursorPosition(event.currentTarget.selectionStart)}
          placeholder="Ask anything, use @agent or /command"
          rows={2}
        />
        <div className="composer-toolbar">
          <div className="composer-tools" aria-label="Composer tools">
            <button type="button" title="Attachments coming later" disabled>
              <Paperclip size={15} />
            </button>
            <button type="button" title="Mention an agent" onClick={() => insertTrigger('@')}>
              <AtSign size={15} />
            </button>
            <button type="button" title="Use a command" onClick={() => insertTrigger('/')}>
              <Slash size={15} />
            </button>
          </div>
          <button className="send-button" disabled={!canSend} title={sending ? 'Sending' : 'Send'}>
            {sending ? <Loader2 size={17} className="spin" /> : <Send size={17} />}
            <span className="sr-only">{sending ? 'Sending' : 'Send'}</span>
          </button>
        </div>
      </div>
    </form>
  );
}

function getActiveToken(value: string, cursorPosition: number): { token: string; start: number; end: number } | null {
  const cursor = Math.max(0, Math.min(cursorPosition, value.length));
  const beforeCursor = value.slice(0, cursor);
  const tokenStart = Math.max(beforeCursor.search(/\S+$/), 0);
  const token = value.slice(tokenStart, cursor);

  if (!token || token.includes(' ') || token.includes('\n') || token.includes('\t')) return null;
  if (!token.startsWith('@') && !token.startsWith('/')) return null;

  return { token, start: tokenStart, end: cursor };
}
