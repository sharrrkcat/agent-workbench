import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { BookmarkPlus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useCogitaStore } from '../../store/useCogitaStore';
import type { MemoryCreate } from '../../types/memory';
import { MemoryEditor } from './MemoryEditor';

export function SaveMemoryAction({ messageId, text, disabled = false }: { messageId: string; text: string; disabled?: boolean }) {
  const { t } = useTranslation('memory');
  const session = useCogitaStore((s) => s.currentSession);
  const [draft, setDraft] = useState<MemoryCreate | null>(null);
  if (!session || session.kind !== 'normal' || !session.bound_persona_id || !text.trim()) return null;
  function open() {
    if (!session || session.kind !== 'normal' || !session.bound_persona_id) return;
    const selection = window.getSelection();
    const node = selection?.anchorNode?.parentElement?.closest('[data-message-id]');
    const selected = node?.getAttribute('data-message-id') === messageId ? selection?.toString().trim() : '';
    const body = (selected || text).trim().slice(0, 2000);
    setDraft({ character_id: session.character_id, persona_id: session.bound_persona_id, session_id: session.session_id,
      pool: 'character', source_message_id: messageId, summary: body.split('\n')[0].slice(0, 160), body, pinned: false });
  }
  return <>
    <Tooltip><TooltipTrigger render={<Button type="button" variant="ghost" size="icon" aria-label={t('fromMessage')} disabled={disabled} onClick={open} />}>
      <BookmarkPlus /></TooltipTrigger><TooltipContent>{t('fromMessage')}</TooltipContent></Tooltip>
    {draft ? <MemoryEditor initial={draft} onClose={() => setDraft(null)} onSaved={() => undefined} /> : null}
  </>;
}
