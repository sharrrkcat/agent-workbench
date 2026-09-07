import { PanelLeftOpen, Settings2, SlidersHorizontal } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useModelsStore } from '../store/useModelsStore';
import { useWorkbenchStore } from '../store/useWorkbenchStore';
import type { SettingsSection } from './SettingsPage';
import { SessionSettingsDialog } from './personas/SessionSettingsDialog';
import { PersonaAvatar } from './personas/ConfigurationFields';

export function ChatHeader({ onOpenSettings, onToggleSidebar }: { onOpenSettings: (section?: SettingsSection) => void; onToggleSidebar: () => void }) {
  const { t } = useTranslation('personas');
  const [editing, setEditing] = useState(false);
  const session = useWorkbenchStore((state) => state.currentSession);
  const updateSession = useWorkbenchStore((state) => state.updateSession);
  const profiles = useModelsStore((state) => state.profiles);
  return <header className="topbar compact-topbar">
    <div className="topbar-left">
      <button type="button" className="icon-button mobile-sidebar-toggle" title={t('sessions')} aria-label={t('sessions')} onClick={onToggleSidebar}><PanelLeftOpen size={18} /></button>
      <div className="chat-title-block"><strong>{session?.title?.trim() || t('newSession')}</strong><small>{session?.waiting_run_id ? t('waiting') : session?.effective.persona_name}</small></div>
      <label className="context-select"><span className="sr-only">{t('conversationMode')}</span><select value={session?.context_mode || 'single_assistant'} disabled={!session} onChange={(e) => void updateSession({ context_mode: e.target.value as 'single_assistant' | 'group_transcript' })}><option value="single_assistant">{t('single')}</option><option value="group_transcript">{t('group')}</option></select></label>
    </div>
    <div className="topbar-actions">
      {session ? <div className="speaker-control"><PersonaAvatar name={session.effective.persona_name} attachmentId={session.effective.avatar_attachment_id} /><select aria-label={t('currentSpeaker')} value={session.current_persona_id} onChange={(e) => void updateSession({ current_persona_id: e.target.value })}>{session.personas.filter((p) => p.enabled).map((p) => <option key={p.persona_id} value={p.persona_id}>{p.name}</option>)}</select></div> : null}
      <select className="chat-model-select" aria-label={t('model')} title={profiles.find((p) => p.id === session?.effective.model_profile_id)?.name || t('unavailable')} value={session?.model_profile_id || ''} disabled={!session} onChange={(e) => void updateSession({ model_profile_id: e.target.value || null })}><option value="">{t('inheritPersona')}</option>{profiles.filter((p) => p.kind === 'llm').map((p) => <option key={p.id} value={p.id} disabled={!p.enabled}>{p.name}</option>)}</select>
      <button className="icon-button" type="button" title={t('sessionSettings')} aria-label={t('sessionSettings')} disabled={!session} onClick={() => setEditing(true)}><SlidersHorizontal size={18} /></button>
      <button className="icon-button" type="button" title={t('settings')} aria-label={t('settings')} onClick={() => onOpenSettings('models')}><Settings2 size={18} /></button>
    </div>
    {editing && session ? <SessionSettingsDialog key={session.session_id} session={session} onClose={() => setEditing(false)} onManagePersonas={() => { if (window.confirm(t('discardChanges'))) { setEditing(false); onOpenSettings('personas'); } }} /> : null}
  </header>;
}
