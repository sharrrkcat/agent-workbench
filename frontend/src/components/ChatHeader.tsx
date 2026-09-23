import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select';
import { Field, FieldLabel } from '@/components/ui/field';
import { PanelLeftOpen, Settings2, SlidersHorizontal } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useModelsStore } from '../store/useModelsStore';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { SettingsSection } from './settings/navigation';
import { SessionSettingsDialog } from './personas/SessionSettingsDialog';
import { ModelSelect, PersonaAvatar } from './personas/ConfigurationFields';

export function ChatHeader({
  onOpenSettings,
  onToggleSidebar,
}: {
  onOpenSettings: (section?: SettingsSection) => void;
  onToggleSidebar: () => void;
}) {
  const { t } = useTranslation('personas');
  const [editing, setEditing] = useState(false);
  const session = useWorkbenchStore((state) => state.currentSession);
  const updateSession = useWorkbenchStore((state) => state.updateSession);
  const profiles = useModelsStore((state) => state.profiles);
  return (
    <header className="topbar compact-topbar">
      <div className="topbar-left">
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                type="button"
                aria-label={t('sessions')}
                onClick={onToggleSidebar}
                variant="ghost"
                size="icon"
                className="mobile-sidebar-toggle"
              />
            }
          >
            <PanelLeftOpen size={18} />
          </TooltipTrigger>
          <TooltipContent>{t('sessions')}</TooltipContent>
        </Tooltip>
        <div className="chat-title-block">
          <strong>{session?.title?.trim() || t('newSession')}</strong>
          <small>{session?.waiting_run_id ? t('waiting') : session?.effective.persona_name}</small>
        </div>
        <Field className="context-select">
          <FieldLabel className="sr-only">{t('conversationMode')}</FieldLabel>
          <Select
            value={session?.context_mode || 'single_assistant'}
            disabled={!session}
            onValueChange={(selected) =>
              void updateSession({
                context_mode: (selected ?? '') as 'single_assistant' | 'group_transcript',
              })
            }
            items={[
              { value: 'single_assistant', label: t('single') },
              { value: 'group_transcript', label: t('group') },
            ]}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="single_assistant">{t('single')}</SelectItem>
              <SelectItem value="group_transcript">{t('group')}</SelectItem>
            </SelectContent>
          </Select>
        </Field>
      </div>
      <div className="topbar-actions">
        {session ? (
          <div className="speaker-control">
            <PersonaAvatar
              name={session.effective.persona_name}
              attachmentId={session.effective.avatar_attachment_id}
            />
            <Select
              value={session.current_persona_id}
              onValueChange={(selected) => void updateSession({ current_persona_id: selected ?? '' })}
              items={session.personas
                .filter((p) => p.enabled)
                .map((p) => ({ value: p.persona_id, label: p.name }))}
            >
              <SelectTrigger aria-label={t('currentSpeaker')}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {session.personas
                  .filter((p) => p.enabled)
                  .map((p) => (
                    <SelectItem key={p.persona_id} value={p.persona_id}>
                      {p.name}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
        ) : null}
        <ModelSelect
          className="chat-model-select"
          profiles={profiles}
          value={session?.model_profile_id ?? null}
          disabled={!session}
          onChange={(model_profile_id) => void updateSession({ model_profile_id })}
        />
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
              />
            }
          >
            <SlidersHorizontal size={18} />
          </TooltipTrigger>
          <TooltipContent>{t('sessionSettings')}</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                type="button"
                aria-label={t('settings')}
                onClick={() => onOpenSettings('models')}
                variant="ghost"
                size="icon"
              />
            }
          >
            <Settings2 size={18} />
          </TooltipTrigger>
          <TooltipContent>{t('settings')}</TooltipContent>
        </Tooltip>
      </div>
      {editing && session ? (
        <SessionSettingsDialog
          key={session.session_id}
          session={session}
          onClose={() => setEditing(false)}
          onManagePersonas={() => {
            setEditing(false);
            onOpenSettings('personas');
          }}
        />
      ) : null}
    </header>
  );
}
