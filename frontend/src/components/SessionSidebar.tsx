import { useConfirmDialog } from '@/hooks/useConfirmDialog';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { MessageSquarePlus, Settings2, Trash2, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function SessionSidebar({
  onOpenSettings,
  open,
  onClose,
}: {
  onOpenSettings: () => void;
  open: boolean;
  onClose: () => void;
}) {
  const { confirm, confirmation } = useConfirmDialog();
  const { t } = useTranslation('personas');
  const sessions = useWorkbenchStore((state) => state.sessions);
  const current = useWorkbenchStore((state) => state.currentSession);
  const select = useWorkbenchStore((state) => state.selectSession);
  const create = useWorkbenchStore((state) => state.createSession);
  const remove = useWorkbenchStore((state) => state.deleteSession);
  return (
    <aside className={`session-sidebar ${open ? 'mobile-open' : ''}`}>
      <div className="sidebar-header">
        <strong>Workbench</strong>
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                type="button"
                aria-label={t('close')}
                onClick={onClose}
                variant="ghost"
                size="icon"
                className="mobile-sidebar-toggle"
              />
            }
          >
            <X size={18} />
          </TooltipTrigger>
          <TooltipContent>{t('close')}</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                type="button"
                aria-label={t('newSession')}
                onClick={() => {
                  void create();
                  onClose();
                }}
                variant="ghost"
                size="icon"
              />
            }
          >
            <MessageSquarePlus size={18} />
          </TooltipTrigger>
          <TooltipContent>{t('newSession')}</TooltipContent>
        </Tooltip>
      </div>
      <div className="session-list">
        {sessions.map((session) => (
          <div
            key={session.session_id}
            className={`session-item ${session.session_id === current?.session_id ? 'selected' : ''}`}
          >
            <Button
              type="button"
              onClick={() => {
                void select(session.session_id);
                onClose();
              }}
              variant="ghost"
              className="session-select"
            >
              <span>{session.title.trim() || t('newSession')}</span>
              <small>
                {t(session.context_mode === 'group_transcript' ? 'group' : 'single')} /{' '}
                {session.effective.persona_name}
              </small>
            </Button>
            {session.session_id === current?.session_id ? (
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button
                      type="button"
                      aria-label={t('deleteSession')}
                      onClick={async () => {
                        if (await confirm(t('deleteSessionConfirm'), { destructive: true }))
                          void remove(session.session_id);
                      }}
                      variant="destructive"
                      size="icon"
                      className="session-delete"
                    />
                  }
                >
                  <Trash2 size={14} />
                </TooltipTrigger>
                <TooltipContent>{t('deleteSession')}</TooltipContent>
              </Tooltip>
            ) : null}
          </div>
        ))}
      </div>
      <div className="sidebar-footer">
        <Button
          type="button"
          onClick={() => {
            onOpenSettings();
            onClose();
          }}
          variant="ghost"
          className="sidebar-settings-button"
        >
          <Settings2 size={16} />
          {t('settings')}
        </Button>
      </div>
      {confirmation}
    </aside>
  );
}
