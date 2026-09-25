import { useTranslation } from 'react-i18next';
import { SidebarTrigger } from '@/components/ui/sidebar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { MessageSquarePlus } from 'lucide-react';
import { useProjectsStore } from '../../store/useProjectsStore';
import { useCogitaStore } from '../../store/useCogitaStore';
import { ProjectEditor } from './ProjectEditor';
import { ResourceLoading, type LeaveGuard } from '../settings/resources/ResourceUI';
import type { SettingsNavigate } from '../settings/navigation';
import { ErrorBanner } from '../ErrorBanner';

export function ProjectPage({ projectId, onNavigate, onLeaveGuardChange, onCreateSession }: {
  projectId: string; onNavigate: SettingsNavigate; onLeaveGuardChange: (guard: LeaveGuard) => void;
  onCreateSession: (projectId: string) => Promise<boolean>;
}) {
  const { t } = useTranslation('personas');
  const project = useProjectsStore((state) => state.projects.find((p) => p.id === projectId));
  const error = useCogitaStore((state) => state.error);
  return <>
    <header className="settings-header">
      <SidebarTrigger />
      <div className="settings-heading min-w-0"><h1 className="truncate">{project?.name || t('projectSettings')}</h1></div>
      {project ? <Badge variant="secondary">{t('projectKinds.' + project.kind)}</Badge> : null}
      {project?.kind === 'workspace' ? <Button variant="outline" onClick={() => void onCreateSession(project.id)}>
        <MessageSquarePlus data-icon="inline-start" />{t('newSession')}
      </Button> : null}
    </header>
    <ErrorBanner />
    <div className="settings-scroll min-h-0 flex-1 overflow-y-auto overscroll-contain">
      <div className="settings-content">
        {project ? <ProjectEditor key={project.id} project={project} kind={project.kind} onSaved={() => undefined}
          onNavigate={onNavigate} onLeaveGuardChange={onLeaveGuardChange} /> :
          <ResourceLoading error={error || undefined} retry={() => void useCogitaStore.getState().activateLocation(projectId)} />}
      </div>
    </div>
  </>;
}
