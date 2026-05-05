import { FormEvent, KeyboardEvent, useMemo, useState } from 'react';
import { Loader2, Send } from 'lucide-react';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import { CommandPalette } from './CommandPalette';

export function ChatInput() {
  const [value, setValue] = useState('');
  const { currentSession, sendMessage, sending } = useWorkbenchStore();

  const canSend = Boolean(currentSession && value.trim() && !sending);

  const mode = useMemo(() => {
    if (value.startsWith('/')) return 'commands';
    if (value.startsWith('@') && value.includes(':')) return 'actions';
    if (value.startsWith('@')) return 'agents';
    return 'none';
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
    <form className="chat-input" onSubmit={submit}>
      <CommandPalette mode={mode} input={value} onPick={setValue} />
      <textarea
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Type a message, @agent, @agent:action, or /command"
        rows={3}
      />
      <button className="send-button" disabled={!canSend} title={sending ? 'Sending' : 'Send'}>
        {sending ? <Loader2 size={17} className="spin" /> : <Send size={17} />}
        <span className="sr-only">{sending ? 'Sending' : 'Send'}</span>
      </button>
    </form>
  );
}
