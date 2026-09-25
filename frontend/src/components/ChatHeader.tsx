import { useState } from 'react';
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

export function ChatHeader({ onOpenSettings }: { onOpenSettings: (route: SettingsRoute) => void }) {
  const { t } = useTranslation('personas');
  const [editing, setEditing] = useState(false);
  const session = useCogitaStore((state) => state.currentSession);
  const updateSession = useCogitaStore((state) => state.updateSession);
  const profiles = useModelsStore((state) => state.profiles);
  const title = session?.title?.trim() || t('newSession');
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
          value={session?.effective.model_profile_id ?? null}
          disabled={!session}
          onChange={(model_profile_id) => void updateSession(session?.kind === 'workspace'
            ? { overrides: { model_profile_id } } : { model_profile_id })}
        />
      </div>
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              type="button"
              aria-label={t('sessionSettings')}
              disabled={!session}
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
      {editing && session ? (
        <SessionSettingsDialog
          key={session.session_id}
          session={session}
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
