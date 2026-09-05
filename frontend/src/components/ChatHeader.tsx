import { Settings2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useModelsStore } from '../store/useModelsStore';
import { useWorkbenchStore } from '../store/useWorkbenchStore';

export function ChatHeader({ onOpenSettings }: { onOpenSettings: (section?: 'general' | 'models' | 'knowledge' | 'worldbook' | 'pet') => void }) {
  const { t } = useTranslation('llm');
  const session = useWorkbenchStore((state) => state.currentSession);
  const updateSession = useWorkbenchStore((state) => state.updateSession);
  const profiles = useModelsStore((state) => state.profiles);
  return <header className="topbar compact-topbar">
    <div className="topbar-left">
      <div className="chat-title-block"><strong>{session?.title?.trim() || t('newSession')}</strong><small>{session?.waiting_run_id ? t('waiting') : t('kinds.llm')}</small></div>
      <label className="context-select"><span className="sr-only">{t('conversationMode')}</span><select value={session?.context_mode || 'single_assistant'} disabled={!session} onChange={(e) => void updateSession({ context_mode: e.target.value as 'single_assistant' | 'group_transcript' })}><option value="single_assistant">{t('singleAssistant')}</option><option value="group_transcript">{t('groupTranscript')}</option></select></label>
    </div>
    <div className="topbar-actions">
      <select className="chat-model-select" aria-label={t('chatModel')} value={session?.model_profile_id || ''} disabled={!session} onChange={(e) => void updateSession({ model_profile_id: e.target.value || null })}><option value="">{t('globalDefault')}</option>{profiles.filter((p) => p.kind === 'llm' && p.enabled).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
      <button className="icon-button" type="button" title={t('settings')} aria-label={t('settings')} onClick={() => onOpenSettings('models')}><Settings2 size={18} /></button>
    </div>
  </header>;
}
