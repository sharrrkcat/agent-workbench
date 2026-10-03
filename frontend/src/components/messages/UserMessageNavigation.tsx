import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { useMessageScroller, useMessageScrollerVisibility } from '@/components/ui/message-scroller';
import type { HistoryUsersPage, HistoryQuery } from '../../types/history';
import { chatApi } from '../../api/chat';
import { useCogitaStore } from '../../store/useCogitaStore';
import { ChevronUp, ChevronDown } from 'lucide-react';

export function UserMessageNavigation() {
  const { t } = useTranslation('chat');
  const { currentAnchorId, visibleMessageIds } = useMessageScrollerVisibility();
  const { scrollToMessage } = useMessageScroller();
  const rail = useRef<HTMLElement>(null);
  const sessionId = useCogitaStore((state) => state.currentSession?.session_id);
  const historyVersion = useCogitaStore((state) => state.historyWindow?.history_version);
  const lastId = useCogitaStore((state) => state.historyWindow?.items[state.historyWindow.items.length - 1]?.id);
  const visible = useCogitaStore((state) => state.historyWindow?.items.find((i) => i.id === visibleMessageIds[0]));
  const loadHistory = useCogitaStore((state) => state.loadHistory);
  const [page, setPage] = useState<HistoryUsersPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [jumpId, setJumpId] = useState<string | null>(null);
  const request = useRef(0);
  const messages = page?.items ?? [];
  const activeId = messages.some((message) => message.id === currentAnchorId)
    ? currentAnchorId : [...messages].reverse().find((message) => message.number <= (visible?.number ?? 0))?.id;
  const activeIndex = messages.findIndex((message) => message.id === activeId);
  async function load(query: HistoryQuery = {}) {
    if (!sessionId) return;
    const current = ++request.current;
    setLoading(true);
    try {
      const result = await chatApi.getHistoryUsers(sessionId, query);
      if (current === request.current) setPage(result);
    } catch (error) {
      if (current === request.current) useCogitaStore.getState().setError(String(error));
    } finally { if (current === request.current) setLoading(false); }
  }
  useEffect(() => {
    setPage(null);
    void load();
    return () => { request.current++; };
  }, [sessionId, historyVersion]);
  useEffect(() => { if (page && !page.has_after) void load(); }, [lastId]);
  useEffect(() => {
    if (visible && page && (visible.number < (page.items[0]?.number ?? 0) && page.has_before ||
      visible.number > (page.items[page.items.length - 1]?.number ?? 0) && page.has_after)) void load({ around: visible.cursor });
  }, [visible?.number]);
  async function jump(id: string, cursor: string) {
    await loadHistory('around', cursor);
    setJumpId(id);
  }
  useLayoutEffect(() => {
    if (!jumpId) return;
    const frame = requestAnimationFrame(() => {
      scrollToMessage(jumpId, { align: 'start', behavior: 'instant' });
      setJumpId(null);
    });
    return () => cancelAnimationFrame(frame);
  }, [jumpId, lastId, scrollToMessage]);

  useEffect(() => {
    const container = rail.current;
    const active = container?.querySelector<HTMLElement>('[aria-current="step"]');
    if (!container || !active) return;
    const outer = container.getBoundingClientRect();
    const inner = active.getBoundingClientRect();
    if (inner.top < outer.top) container.scrollTop += inner.top - outer.top;
    else if (inner.bottom > outer.bottom) container.scrollTop += inner.bottom - outer.bottom;
  }, [activeId]);

  if (messages.length < 2 && !page?.has_before && !page?.has_after) return null;
  return (
    <nav ref={rail} className="user-message-navigation" aria-label={t('userMessageNavigation')}>
      {page?.has_before && <Button variant="ghost" size="icon-sm" aria-label={t('loadEarlier')} disabled={loading}
        onClick={() => void load({ before: page.before_cursor! })}><ChevronUp /></Button>}
      {messages.map((message, index) => {
        const number = message.number;
        const summary = message.summary || t('userMessageNumber', { number });
        return (
          <Tooltip key={message.id}>
            <TooltipTrigger render={
              <Button variant="ghost" size="icon" className="user-message-tick h-2 w-11 justify-start pl-[10px] pointer-coarse:min-h-2"
                aria-label={t('jumpToUserMessage', { number, summary })}
                aria-current={message.id === activeId ? 'step' : undefined}
                data-adjacent={activeIndex >= 0 && Math.abs(index - activeIndex) === 1 ? '' : undefined}
                onClick={() => void jump(message.id, message.cursor)} />
            }><span aria-hidden="true" /></TooltipTrigger>
            <TooltipContent side="right" className="max-w-64 break-words">{summary}</TooltipContent>
          </Tooltip>
        );
      })}
      {page?.has_after && <Button variant="ghost" size="icon-sm" aria-label={t('loadLater')} disabled={loading}
        onClick={() => void load({ after: page.after_cursor! })}><ChevronDown /></Button>}
    </nav>
  );
}
