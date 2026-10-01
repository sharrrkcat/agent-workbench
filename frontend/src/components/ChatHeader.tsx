import { useLayoutEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { SlidersHorizontal } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { SidebarTrigger } from '@/components/ui/sidebar';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { useModelsStore } from '../store/useModelsStore';
import { useCogitaStore } from '../store/useCogitaStore';
import type { SettingsRoute } from './settings/navigation';
import { SessionSettingsDialog } from './personas/SessionSettingsDialog';
import { ModelSelect } from './personas/ConfigurationFields';
import { useChatConfiguration } from '../hooks/useChatConfiguration';

export function ChatHeader({ onOpenSettings }: { onOpenSettings: (route: SettingsRoute) => void }) {
  const { t } = useTranslation('personas');
  const [editing, setEditing] = useState(false);
  const session = useCogitaStore((state) => state.currentSession);
  const draft = useCogitaStore((state) => state.chatDraft);
  const sending = useCogitaStore((state) => state.sending);
  const sessionLoad = useCogitaStore((state) => state.sessionLoad);
  const sessionEpoch = useCogitaStore((state) => state.sessionEpoch);
  useLayoutEffect(() => setEditing(false), [sessionEpoch]);
  const unavailable = !!sessionLoad && sessionLoad.status !== 'ready';
  const target = session ?? draft;
  const configuration = useChatConfiguration();
  const updateSession = useCogitaStore((state) => state.updateSession);
  const profiles = useModelsStore((state) => state.profiles);
  const title = target ? target.title.trim() || t('newSession')
    : sessionLoad ? t(sessionLoad.status === 'error' ? 'chat:loadFailed' : 'common:loading') : t('newSession');
  return (
    <header className="topbar">
      <Tooltip>
        <TooltipTrigger render={<SidebarTrigger className="sidebar-toggle" />} />
        <TooltipContent>{t('toggleSidebar')}</TooltipContent>
      </Tooltip>
      <h1 className="chat-title" title={title}>
        {title}
      </h1>
      <div className="chat-model-control">
        <ModelSelect
          className="chat-model-select w-full min-w-0"
          profiles={profiles}
          value={configuration?.model_profile_id ?? null}
          disabled={!target || sending || unavailable}
          onChange={(model_profile_id) => void updateSession(target?.kind === 'workspace'
            ? { overrides: { model_profile_id } } : { model_profile_id })}
        />
      </div>
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              type="button"
              aria-label={t('sessionSettings')}
              disabled={!target || sending || unavailable}
              onClick={() => setEditing(true)}
              variant="ghost"
              size="icon"
              className="session-settings-trigger"
            />
          }
        >
          <SlidersHorizontal />
        </TooltipTrigger>
        <TooltipContent>{t('sessionSettings')}</TooltipContent>
      </Tooltip>
      {editing && target ? (
        <SessionSettingsDialog
          key={session?.session_id ?? 'draft'}
          session={target}
          onClose={() => setEditing(false)}
          onManagePersonas={() => {
            setEditing(false);
            onOpenSettings({ section: 'personas', view: 'agent' });
          }}
        />
      ) : null}
    </header>
  );
}
