import { FormEvent, KeyboardEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { AtSign, Check, ChevronDown, Loader2, Paperclip, Send, Slash } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { CommandPalette } from './CommandPalette';

export function ChatInput() {
  const [value, setValue] = useState('');
  const [cursorPosition, setCursorPosition] = useState(0);
  const [suggestionsDismissed, setSuggestionsDismissed] = useState(false);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const formRef = useRef<HTMLFormElement | null>(null);
  const modelSelectorRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const { currentSession, llmProfiles, sendMessage, sending, updateSessionLlmProfile } = useWorkbenchStore();

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
      if (!modelSelectorRef.current?.contains(event.target as Node)) {
        setModelMenuOpen(false);
      }
    }
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, []);

  useEffect(() => {
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') {
        setModelMenuOpen(false);
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
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

  function selectModel(profileId: string | null) {
    setModelMenuOpen(false);
    void updateSessionLlmProfile(profileId);
  }

  const selectedModelLabel = modelSelectorLabel(currentSession?.llm_profile_id || null, llmProfiles);
  const enabledProfiles = llmProfiles.filter((profile) => profile.enabled);

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
          <div className="composer-actions">
            <div ref={modelSelectorRef} className="model-selector-wrap">
              <button
                className="model-selector-pill"
                type="button"
                title={modelSelectorTitle(currentSession?.llm_profile_id || null, llmProfiles)}
                disabled={!currentSession}
                aria-haspopup="menu"
                aria-expanded={modelMenuOpen}
                onClick={() => setModelMenuOpen((open) => !open)}
              >
                <strong>{selectedModelLabel}</strong>
                <ChevronDown size={13} aria-hidden="true" />
              </button>
              {modelMenuOpen ? (
                <div className="model-selector-menu" role="menu">
                  <button
                    type="button"
                    role="menuitemradio"
                    aria-checked={!currentSession?.llm_profile_id}
                    className={!currentSession?.llm_profile_id ? 'selected' : ''}
                    onClick={() => selectModel(null)}
                  >
                    <span>Default</span>
                    {!currentSession?.llm_profile_id ? <Check size={14} /> : null}
                  </button>
                  {enabledProfiles.map((profile) => {
                    const selected = currentSession?.llm_profile_id === profile.id;
                    return (
                      <button
                        key={profile.id}
                        type="button"
                        role="menuitemradio"
                        aria-checked={selected}
                        className={selected ? 'selected' : ''}
                        onClick={() => selectModel(profile.id)}
                      >
                        <span>{profile.name || profile.alias}</span>
                        {selected ? <Check size={14} /> : null}
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>
            <button className="send-button" disabled={!canSend} title={sending ? 'Sending' : 'Send'}>
              {sending ? <Loader2 size={17} className="spin" /> : <Send size={17} />}
              <span className="sr-only">{sending ? 'Sending' : 'Send'}</span>
            </button>
          </div>
        </div>
      </div>
    </form>
  );
}

function modelSelectorTitle(profileId: string | null, profiles: { id: string; name: string; alias: string; model_id: string }[]): string {
  if (!profileId) return 'Default uses the agent manifest or global LLM fallback';
  const profile = profiles.find((item) => item.id === profileId);
  if (!profile) return 'Missing profile';
  return `${profile.name || profile.alias} - ${profile.model_id}`;
}

function modelSelectorLabel(profileId: string | null, profiles: { id: string; name: string; alias: string }[]): string {
  if (!profileId) return 'Default';
  const profile = profiles.find((item) => item.id === profileId);
  return profile ? profile.name || profile.alias : 'Missing profile';
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
