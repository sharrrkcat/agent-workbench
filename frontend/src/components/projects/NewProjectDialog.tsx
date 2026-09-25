import { useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import type { Project, ProjectKind } from '../../types/projects';
import type { LeaveGuard } from '../settings/resources/ResourceUI';
import type { SettingsNavigate } from '../settings/navigation';
import { ProjectEditor } from './ProjectEditor';

export function NewProjectDialog({ kind, onClose, onSaved, onNavigate }: {
  kind: ProjectKind; onClose: () => void; onSaved: (project: Project) => void; onNavigate: SettingsNavigate;
}) {
  const { t } = useTranslation('personas');
  const guard = useRef<LeaveGuard>(async () => true);
  const register = useCallback((value: LeaveGuard) => { guard.current = value; }, []);
  const leave = async (url?: string) => {
    if (!(await guard.current(new URL(url || window.location.href, window.location.href)))) return false;
    if (url && !(await onNavigate(url))) return false;
    onClose();
    return true;
  };
  return <Dialog open onOpenChange={(open) => { if (!open) void leave(); }}>
    <DialogContent className="sm:max-w-3xl">
      <DialogHeader><DialogTitle>{t(kind === 'workspace' ? 'newWorkspace' : 'newTimeline')}</DialogTitle></DialogHeader>
      <ProjectEditor kind={kind} dialog onSaved={onSaved} onNavigate={leave} onLeaveGuardChange={register} />
    </DialogContent>
  </Dialog>;
}
