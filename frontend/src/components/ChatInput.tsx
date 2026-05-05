import { FormEvent, KeyboardEvent, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { AtSign, Loader2, Paperclip, Send, Slash } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { CommandPalette } from './CommandPalette';

export function ChatInput() {
  const [value, setValue] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const { currentSession, sendMessage, sending } = useWorkbenchStore();

  const canSend = Boolean(currentSession && value.trim() && !sending);

  const mode = useMemo(() => {
    if (value.startsWith('/')) return 'commands';
    if (value.startsWith('@') && value.includes(':')) return 'actions';
    if (value.startsWith('@')) return 'agents';
    return 'none';
  }, [value]);

  useLayoutEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    const nextHeight = Math.min(textarea.scrollHeight, 180);
    textarea.style.height = `${Math.max(nextHeight, 44)}px`;
    textarea.style.overflowY = textarea.scrollHeight > 180 ? 'auto' : 'hidden';
  }, [value]);

  function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!canSend) return;
    const content = value;
    setValue('');
    void sendMessage(content);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <form className="composer-shell" onSubmit={submit}>
      <div className="composer-card">
        <CommandPalette mode={mode} input={value} onPick={setValue} />
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask anything, use @agent or /command"
          rows={2}
        />
        <div className="composer-toolbar">
          <div className="composer-tools" aria-label="Composer tools">
            <button type="button" title="Attachments coming later" disabled>
              <Paperclip size={15} />
            </button>
            <button type="button" title="Mention an agent" onClick={() => setValue((current) => (current ? current : '@'))}>
              <AtSign size={15} />
            </button>
            <button type="button" title="Use a command" onClick={() => setValue((current) => (current ? current : '/'))}>
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
